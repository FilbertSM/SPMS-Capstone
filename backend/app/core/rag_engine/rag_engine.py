import os
import re
import uuid
import pickle
import shutil
from dotenv import load_dotenv
from langchain_chroma import Chroma

from dotenv import load_dotenv
# Data & Ingestion Dependencies
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

# Vector & Reranking Dependencies
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.retrievers import BM25Retriever
from sentence_transformers import CrossEncoder

# LLM Dependencies
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate

# Explicitly pathing to the new storage route
STORAGE_BASE = "storage"
CHROMA_PATH = os.path.join(STORAGE_BASE, "vector_stores", "SPMS_Master_DB") # Renamed to reflect master status
STATE_FILE = os.path.join(STORAGE_BASE, "system_states", "system_state.pkl")

def run_ingestion_pipeline(source_pdf_path: str, machine_type: str):
    """Executes parent-child splitting, text parsing, and appends storage files with a machine metadata tag."""
    print(f"[RAG Ingestion] Appending document to {machine_type} archive...")
    
    # 1. Ensure directories exist without destroying existing Chroma databases
    os.makedirs(os.path.dirname(CHROMA_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

    # Load Existing State if it exists to append data smoothly
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'rb') as f:
            state = pickle.load(f)
        parent_dictionary = state.get("parent_dictionary", {})
        all_child_docs = state.get("all_child_docs", [])
    else:
        parent_dictionary = {}
        all_child_docs = []

    # 2. Document Extraction & Cleaning
    loader = PyMuPDFLoader(source_pdf_path)
    raw_documents = loader.load()
    
    clean_documents = []
    for doc in raw_documents:
        text = doc.page_content
        if text.count('/') > 50 or len(text.strip()) < 15:
            continue
        text = re.sub(r'\n{3,}', '\n\n', text)
        doc.page_content = text
        clean_documents.append(doc)
    
    parent_splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)
    
    # THE FIX: Upsize the Scouts so they can hold both keywords and data tables!
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,        # Increased from 250 to 800
        chunk_overlap=150,     # Increased overlap to keep tables glued to their headers
        separators=["\n\n", "\n", ".", " "]
    )
    
    parent_documents = parent_splitter.split_documents(clean_documents)
    new_child_docs = []
    
    for parent_doc in parent_documents:
        # Create a localized parent ID incorporating the machine tag for explicit tracing
        parent_id = f"{machine_type.upper()}_{str(uuid.uuid4())}"
        parent_dictionary[parent_id] = parent_doc.page_content
        
        child_texts = child_splitter.split_text(parent_doc.page_content)
        for child_text in child_texts:
            child_doc = Document(
                page_content=child_text,
                metadata={
                    "parent_id": parent_id,
                    "source": parent_doc.metadata.get("source", "Unknown"),
                    "page": parent_doc.metadata.get("page", 0),
                    "machine": machine_type.upper()  # STICKY NOTE: Essential for metadata queries
                }
            )
            new_child_docs.append(child_doc)
            all_child_docs.append(child_doc) # Keep track globally for complete BM25 re-compilation
            
    # 3. Embedding Compilation & Vector Injection
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2", model_kwargs={'device': 'cpu'})
    
    # Passing an existing directory path triggers Chroma to append automatically
    vectorstore = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
    vectorstore.add_documents(documents=new_child_docs)
    
    # 4. Re-compile complete BM25 retriever corpus to contain old and new docs
    keyword_retriever = BM25Retriever.from_documents(all_child_docs)
    keyword_retriever.k = 15  # Pull slightly more to allow manual filtering on machine tags
    
    # 5. Serialize Updated System States
    with open(STATE_FILE, 'wb') as f:
        pickle.dump({
            "keyword_retriever": keyword_retriever,
            "parent_dictionary": parent_dictionary,
            "all_child_docs": all_child_docs
        }, f)
    print(f"[RAG Ingestion] {machine_type} manual successfully appended to local disk storage.")


class SPMSChatEngine:
    def __init__(self):
        load_dotenv()
        
        # Guard initialization if files haven't been compiled yet
        if not os.path.exists(STATE_FILE) or not os.path.exists(CHROMA_PATH):
            raise FileNotFoundError("RAG storage files missing. Please upload a system manual first.")

        # Load RAM states
        with open(STATE_FILE, 'rb') as f:
            state = pickle.load(f)
        self.keyword_retriever = state["keyword_retriever"]
        self.parent_dictionary = state["parent_dictionary"]
        
        # Load Chroma Vector Database
        embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2", model_kwargs={'device': 'cpu'})
        self.vectorstore = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
        self.vector_retriever = self.vectorstore.as_retriever(search_kwargs={"k": 5})
        
        # Load Cross-Encoder Scoring System
        self.cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2', max_length=512)
        
        # Setup Core Gemini Target Model
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-3.1-flash-lite",
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            temperature=0.0,
            timeout=60,    # Give up after 60 seconds instead of hanging forever
            max_retries=1  # Do not enter a silent retry loop!
        )
        
        self.generation_prompt = PromptTemplate.from_template(
            """You are a precise industrial engineering AI. Answer the user's question using ONLY the provided technical context. 
    If the answer is not contained in the context, say "I cannot find the answer in the manual." Do not guess.

    FORMATTING RULES:
    1. Use **bold text** for specific limits, metrics, or section headers (e.g., **Preparation:**).
    2. Use bullet points (*) for lists and safety warnings.
    3. Use numbered lists (1., 2., 3.) for step-by-step procedures.
    4. Use blockquotes (>) for critical safety hazards.
    5. Use Markdown tables for comparing properties, alarms, or severity levels.

    Context:
    {context}

    Question: {question}
    
    Answer:"""
        )

    def retrieve_and_rerank(self, query: str, machine_filter: str = None, top_k: int = 3) -> list[str]:
        """Executes a filtered hybrid search combining vector space and keyword indices via RRF."""
        
        # --- 1. DYNAMIC VECTOR SEARCH (WITH NATIVE METADATA FILTER) ---
        if machine_filter:
            # Re-configure retriever on-the-fly to apply Chroma's standard where-clause filter
            vector_results = self.vectorstore.as_retriever(
                search_kwargs={
                    "k": 10,  # Grab a slightly wider window for high-relevance candidates
                    "filter": {"machine": machine_filter.upper()}
                }
            ).invoke(query)
        else:
            # Fallback to the default global retriever if no machine is selected
            vector_results = self.vector_retriever.invoke(query)
            
        # --- 2. KEYWORD SEARCH (WITH PYTHON-SIDE POST-FILTERING) ---
        raw_keyword_results = self.keyword_retriever.invoke(query)
        
        if machine_filter:
            target_machine = machine_filter.upper()
            # Intercept the document array and drop any snippet that doesn't match the selected machine tag
            keyword_results = [
                doc for doc in raw_keyword_results 
                if doc.metadata.get("machine") == target_machine
            ]
        else:
            keyword_results = raw_keyword_results

        # --- 3. RECIPROCAL RANK FUSION (RRF) ---
        fused_scores = {}
        
        for rank, doc in enumerate(vector_results):
            parent_id = doc.metadata.get("parent_id")
            if parent_id:
                fused_scores[parent_id] = fused_scores.get(parent_id, 0) + 1 / (rank + 60)
                
        for rank, doc in enumerate(keyword_results):
            parent_id = doc.metadata.get("parent_id")
            if parent_id:
                fused_scores[parent_id] = fused_scores.get(parent_id, 0) + 1 / (rank + 60)

        candidate_ids = sorted(fused_scores.keys(), key=lambda x: fused_scores[x], reverse=True)[:10]
        
        # Grab the actual text blocks for those top 10 IDs
        candidate_docs = [self.parent_dictionary[doc_id] for doc_id in candidate_ids if doc_id in self.parent_dictionary]
        
        if not candidate_docs:
            return []

        # --- THE CROSS-ENCODER MATH IS BACK ---
        print(f"[Tracer] 1.5. Cross-Encoder is reading {len(candidate_docs)} chunks...")
        
        # Pair the user's query with every single document block
        cross_inp = [[query, doc] for doc in candidate_docs]
        
        # Run the heavy CPU matrix math to predict true relevance
        scores = self.cross_encoder.predict(cross_inp)
        
        # Zip the scores with the documents and sort them descending (highest score first)
        scored_docs = list(zip(scores, candidate_docs))
        scored_docs.sort(key=lambda x: x[0], reverse=True)
        
        # Return only the absolute best blocks
        return [doc for score, doc in scored_docs[:top_k]]
    
    def ask(self, question: str, machine_filter: str = None, target_language: str = "English") -> dict:
        
        # --- 1. CONDITIONAL QUERY TRANSLATION ---
        if target_language.lower() != "english":
            print(f"\n[Tracer] 0. Translating query from {target_language} to English...")
            trans_prompt = f"Translate this technical factory question into English. Return ONLY the translation, no other text: {question}"
            raw_content = self.llm.invoke(trans_prompt).content
            
            if isinstance(raw_content, list):
                search_query = raw_content[0].get("text", str(raw_content[0])).strip()
            else:
                search_query = raw_content.strip()
        else:
            print("\n[Tracer] 0. English selected. Skipping translation.")
            search_query = question
            
        print(f"[Tracer] 0.5. Search Query is now: '{search_query}'")

        # --- 2. LOCAL DATABASE RETRIEVAL ---
        print(f"\n[Tracer] 1. Initiating Vector/BM25 Search...")
        print(f"[Tracer] 1.5. STRICT FILTER APPLIED: Searching ONLY inside '{machine_filter}' documents.")
        
        best_context_blocks = self.retrieve_and_rerank(search_query, machine_filter=machine_filter, top_k=3)
        
        if best_context_blocks:
            print(f"\n[Tracer] 2. SUCCESS: Cross-Encoder approved {len(best_context_blocks)} high-quality context chunks.")
            context_string = "\n\n---\n\n".join(best_context_blocks)
            
            # Print a preview of what we are handing to Gemini (first 500 characters)
            print(f"[Tracer] 2.5. CONTEXT PREVIEW INJECTED INTO PROMPT:\n{'-'*50}\n{context_string[:500]}...\n{'-'*50}\n")
        else:
            print(f"\n[Tracer] 2. FAILURE: No context found! The database returned 0 chunks for '{machine_filter}'.")
            context_string = "No Context Found."

        # --- 3. FINAL OUTPUT GENERATION ---
        print(f"[Tracer] 3. Generating final response in {target_language}...")
        
        generation_prompt = f"""
        You are a strict technical assistant for industrial machinery.
        Answer the user's question using ONLY the provided technical context.
        Do not guess or hallucinate.
        
        FORMATTING RULES:
        1. Use **bold text** for specific limits, metrics, or section headers (e.g., **Preparation:**).
        2. Use bullet points (*) for lists and safety warnings.
        3. Use numbered lists (1., 2., 3.) for step-by-step procedures.
        4. Use blockquotes (>) for critical safety hazards.
        5. Use Markdown tables for comparing properties, alarms, or severity levels.
        
        CRITICAL INSTRUCTION: You must write your final response and apply all formatting entirely in {target_language}.
        
        Context:
        {context_string}
        
        Question: {question}
        
        Answer:
        """
        
        raw_response = self.llm.invoke(generation_prompt)
        usage = raw_response.usage_metadata or {}
        
        # --- THE JSON CLEANUP FIX ---
        final_text = raw_response.content
        if isinstance(final_text, list):
            final_text = final_text[0].get("text", str(final_text[0]))
            
        print(f"[Tracer] 4. Generation Complete. Sending answer back to React UI.\n")
        
        return {
            "answer": final_text,
            "metadata": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "machine_filter_applied": machine_filter,
                "target_language": target_language
            }
        }