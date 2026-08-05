import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// ==========================================
// 1. API HOOK IMPLEMENTATIONS (AXIOS)
// ==========================================
const uploadEngineeringManual = async (file, currentMachine, onUploadProgress) => {
    const formData = new FormData();
    formData.append('file', file);
    
    // It attaches the machine string (e.g. "FETTE") as the metadata tag
    formData.append('machine_type', currentMachine); 

    const response = await axios.post('http://127.0.0.1:8000/api/rag/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: onUploadProgress // This keeps your progress bar working!
    });
    
    return response.data;
};

const sendChatQuestion = async (trimmedQuery, currentMachine, targetLanguage) => {
  try {
    const response = await axios.post('http://127.0.0.1:8000/api/rag/chat', {
      question: trimmedQuery,
      machine_filter: currentMachine,
      target_language: targetLanguage
    }, {
      timeout: 120000, 
      headers: {
        'Content-Type': 'application/json'
      }
    });
    
    return response.data;
  } catch (error) {
    console.error("Full Backend Error:", error);
    if (error.response) throw new Error(`Server Error: ${error.response.data.detail || error.message}`);
    else if (error.request) throw new Error("The AI is taking too long to process. Please try again.");
    else throw new Error(error.message);
  }
};

// ==========================================
// 2. MAIN DASHBOARD COMPONENT
// ==========================================
const SPMSChatDashboard = () => {
  // Chat States
  const [messages, setMessages] = useState(() => {
    const savedSession = localStorage.getItem('spms_chat_history');
    if (savedSession) {
      try {
        const parsedMessages = JSON.parse(savedSession);
        // Map over the array to convert the timestamp strings back into actual Date objects
        return parsedMessages.map(msg => ({
          ...msg,
          timestamp: new Date(msg.timestamp)
        }));
      } catch (error) {
        console.error("Error parsing local storage history:", error);
        return [];
      }
    }
    return [];
  });

  const [inputQuery, setInputQuery] = useState('');
  const [isQuerying, setIsQuerying] = useState(false);
  
  // Upload States
  const [selectedFile, setSelectedFile] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [systemNotification, setSystemNotification] = useState({ text: '', type: '' });

  const [activeMachine, setActiveMachine] = useState('PMA');

  const chatBottomRef = useRef(null);

  const [selectedLanguage, setSelectedLanguage] = useState("English");

// Dynamic Equipment States
  const [machineList, setMachineList] = useState(['PMA', 'Fette Tablet Press', 'Wetmill']);
  const [isAddingCustom, setIsAddingCustom] = useState(false);
  const [customMachineName, setCustomMachineName] = useState('');

  const clearChatHistory = () => {
    setMessages([]);
    localStorage.removeItem('spms_chat_history');
  };


  // Auto-scroll chat window to the latest message
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isQuerying]);

  useEffect(() => {
    localStorage.setItem('spms_chat_history', JSON.stringify(messages));
  }, [messages]);

  // Handle File Selection
  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file && file.type === 'application/pdf') {
      setSelectedFile(file);
      setSystemNotification({ text: '', type: '' });
    } else {
      setSelectedFile(null);
      setSystemNotification({ text: 'Invalid file format. Please select a .pdf file.', type: 'error' });
    }
  };

// Handle Manual Upload
  const handleManualUpload = async () => {
    if (!selectedFile) return;
    setIsUploading(true);
    setUploadProgress(0);
    setSystemNotification({ text: 'Initializing pipeline & structuring document chunks...', type: 'info' });

    try {
      // THE FIX: We added "activeMachine" right after "selectedFile"
      const data = await uploadEngineeringManual(selectedFile, activeMachine, (progressEvent) => {
        const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
        setUploadProgress(percentCompleted);
      });
      
      setSystemNotification({ text: `Success: ${data.message}`, type: 'success' });
      setSelectedFile(null);
    } catch (error) {
      setSystemNotification({ text: error.message, type: 'error' });
    } finally {
      setIsUploading(false);
    }
  };

  // Handle Chat Submission
  const handleSendMessage = async (e) => {
    e.preventDefault();
    const trimmedQuery = inputQuery.trim();
    if (!trimmedQuery || isQuerying) return;

    //  const botResponse = await sendChatQuestion(trimmedQuery, activeMachine, selectedLanguage);

    // Append user query to thread immediately
    const userMessage = { sender: 'user', text: trimmedQuery, timestamp: new Date() };
    setMessages((prev) => [...prev, userMessage]);
    setInputQuery('');
    setIsQuerying(true);

    try {
      // 2. Await the backend
      const responseData = await sendChatQuestion(trimmedQuery, activeMachine, selectedLanguage);
      
      // THE FIX 1: Protect against undefined/null responses
      if (!responseData) {
        throw new Error("Backend returned an empty response.");
      }

      let safeText = "No response text found.";
      
      // THE FIX 2: Use optional chaining (?.) just in case it's a raw string and has no .answer property
      const targetData = responseData?.answer || responseData;

      // 3. Extract the safe text
      if (typeof targetData === 'string') {
        safeText = targetData;
      } else if (typeof targetData === 'object' && targetData !== null) {
        // Fallback just in case it returns an unexpected JSON structure
        safeText = JSON.stringify(targetData);
      }

      // 4. Append the bot's response to the chat
      const botMessage = { sender: 'bot', text: safeText, timestamp: new Date() };
      setMessages((prev) => [...prev, botMessage]);

    } catch (error) {
      console.error("Chat Error:", error);
      
      // Tell the user something went wrong instead of failing silently
      const errorMessage = { 
        sender: 'bot', 
        text: "⚠️ Network Error: Could not reach the AI. Please try again.", 
        timestamp: new Date() 
      };
      setMessages((prev) => [...prev, errorMessage]);

    } finally {
      // THE FIX 3: This ALWAYS runs, even if the try block crashes. 
      // It guarantees your UI will never freeze!
      setIsQuerying(false);
    }
  };

  const handleClearChat = () => {
    if (window.confirm("Are you sure you want to clear the chat history?")) {
      setMessages([]);
      localStorage.removeItem('spms_chat_history');
    }
  };

  return (
    <div className="flex flex-col h-screen font-sans bg-slate-100">
      
      {/* Top Header Bar */}
      <header className="py-4 px-5 bg-slate-800 text-white flex justify-between items-center shadow-md z-10">
        <h2 className="m-0 text-lg font-medium tracking-wide">SPMS | Document Loader and Chatbot</h2>
      </header>

      {/* Main Workspace Layout */}
      <div className="flex flex-1 overflow-hidden">
        
        {/* ========================================== */}
        {/* Left Control Panel: Document Operations    */}
        {/* ========================================== */}
        <aside className="w-[360px] bg-white border-r border-slate-200 flex flex-col shadow-[2px_0_8px_-4px_rgba(0,0,0,0.05)] z-10 overflow-y-auto shrink-0">
          
          {/* Section Header */}
          <div className="p-6 border-b border-slate-100 shrink-0">
            <h3 className="m-0 mb-1.5 text-3xl font-bold text-slate-800">Document Uploader</h3>
            <p className="text-base text-slate-500 m-0 leading-relaxed">
              Upload technical manuals to update the Chroma vector index.
            </p>
          </div>

          {/* Main Form Area */}
          <div className="p-6 flex flex-col gap-6">
            
            {/* 1. Equipment Dropdown */}
            <div className="flex flex-col gap-2">
              <label className="text-[14px] font-bold text-slate-500 uppercase tracking-wider">
                Target Machine
              </label>
              
              {!isAddingCustom ? (
                <select
                  value={activeMachine}
                  onChange={(e) => {
                    if (e.target.value === "ADD_NEW") {
                      setIsAddingCustom(true);
                    } else {
                      setActiveMachine(e.target.value);
                    }
                  }}
                  className="w-full p-2.5 border border-slate-300 rounded-lg bg-slate-50 text-slate-800 text-lg outline-none cursor-pointer hover:border-blue-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 transition-all shadow-sm"
                >
                  {machineList.map(machine => (
                    <option key={machine} value={machine}>{machine}</option>
                  ))}
                  <option disabled>──────────</option>
                  <option value="ADD_NEW" className="text-blue-600 font-semibold">+ Add New Equipment...</option>
                </select>
              ) : (
                <div className="flex gap-2">
                  <input 
                    type="text" 
                    placeholder="Type machine name..."
                    value={customMachineName}
                    onChange={(e) => setCustomMachineName(e.target.value)}
                    className="flex-1 p-2.5 border border-slate-300 rounded-lg bg-slate-50 text-slate-800 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                    autoFocus
                  />
                  <button 
                    onClick={() => {
                      if (customMachineName.trim()) {
                        const newMachine = customMachineName.trim();
                        setMachineList(prev => [...prev, newMachine]);
                        setActiveMachine(newMachine);
                        setIsAddingCustom(false);
                        setCustomMachineName('');
                      }
                    }}
                    className="py-2.5 px-3 bg-emerald-500 text-white border-none rounded-lg cursor-pointer font-bold text-xs hover:bg-emerald-600 transition-colors shadow-sm"
                  >
                    Save
                  </button>
                  <button 
                    onClick={() => {
                      setIsAddingCustom(false);
                      setCustomMachineName('');
                    }}
                    className="py-2.5 px-3 bg-slate-200 text-slate-600 border-none rounded-lg cursor-pointer font-bold text-xs hover:bg-slate-300 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              )}
              <p className="text-[14px] text-slate-400 m-0 mt-1">
                Isolates knowledge base context to this module.
              </p>
            </div>

            {/* 2. Modern Dropzone & Button Group */}
            <div className="flex flex-col gap-3">
              {/* Dropzone */}
              <div className={`relative flex flex-col items-center justify-center p-8 border-2 border-dashed rounded-xl transition-all duration-200 group ${
                selectedFile 
                  ? 'border-blue-400 bg-blue-50' 
                  : 'border-slate-300 bg-slate-50 hover:bg-slate-100 hover:border-slate-400'
              }`}>
                <input 
                  type="file" 
                  accept=".pdf" 
                  id="file-upload" 
                  onChange={handleFileChange} 
                  disabled={isUploading}
                  className="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-not-allowed z-10" 
                />
                
                {/* Dynamic Dropzone Content */}
                {!selectedFile ? (
                  <>
                    <div className="text-3xl mb-2 opacity-50 group-hover:scale-110 transition-transform duration-200">📄</div>
                    <span className="text-sm font-semibold text-slate-700">Click to browse PDF</span>
                    <span className="text-[11px] text-slate-500 mt-1">Maximum file size: 50MB</span>
                  </>
                ) : (
                  <>
                    <div className="text-3xl mb-2">✅</div>
                    <span className="text-sm font-bold text-blue-700 text-center truncate w-full px-2">
                      {selectedFile.name}
                    </span>
                    <span className="text-[11px] text-blue-500 mt-1 font-medium">Click to change file</span>
                  </>
                )}
              </div>

              {/* Action Button */}
              <button
                onClick={handleManualUpload}
                disabled={!selectedFile || isUploading}
                className={`w-full py-3 px-4 rounded-lg font-bold text-lg shadow-sm transition-all flex items-center justify-center gap-2 ${
                  !selectedFile || isUploading 
                    ? 'bg-slate-200 text-slate-400 cursor-not-allowed' 
                    : 'bg-blue-600 text-white hover:bg-blue-700 hover:shadow-md hover:shadow-blue-200 active:scale-[0.98]'
                }`}
              >
                {isUploading ? (
                  <>
                    <span className="animate-spin text-lg">⏳</span> Compiling...
                  </>
                ) : (
                  'Upload & Parse Manual'
                )}
              </button>
            </div>

            {/* Progress Bar (Only visible when uploading) */}
            {isUploading && (
              <div className="p-4 bg-slate-50 rounded-lg border border-slate-100">
                <div className="flex justify-between text-[11px] font-semibold text-slate-600 mb-2">
                  <span>Parsing Embeddings</span>
                  <span>{uploadProgress}%</span>
                </div>
                <div className="w-full bg-slate-200 h-2 rounded-full overflow-hidden">
                  <div 
                    className="bg-blue-500 h-full transition-all duration-300 ease-out relative" 
                    style={{ width: `${uploadProgress}%` }}
                  >
                    <div className="absolute top-0 left-0 bottom-0 right-0 bg-white/20 animate-pulse"></div>
                  </div>
                </div>
              </div>
            )}

            {/* Operation Status Notifications */}
            {systemNotification.text && (
              <div className={`p-3 rounded-lg border text-xs leading-relaxed transition-all shadow-sm mt-auto ${
                systemNotification.type === 'success' 
                  ? 'bg-emerald-50 text-emerald-800 border-emerald-200' 
                  : systemNotification.type === 'error' 
                  ? 'bg-rose-50 text-rose-800 border-rose-200' 
                  : 'bg-blue-50 text-blue-800 border-blue-200'
              }`}>
                {systemNotification.text}
              </div>
            )}

          </div>
        </aside>

        {/* ========================================== */}
        {/* Right Section: Conversational Chat Area    */}
        {/* ========================================== */}
        <main className="flex-1 flex flex-col bg-slate-50">
          
          {/* --- NEW CHAT HEADER --- */}
          <div className="flex justify-between items-center py-5 px-8 bg-white border-b border-slate-200 shadow-sm z-0">
            <h2 className="m-0 text-xl font-bold text-slate-800 tracking-wide">
              SPMS Chatbot <span className="text-xl font-medium text-slate-600 ml-2">({activeMachine})</span>
            </h2>
            
            {/* Top Right Controls Container */}
            <div className="flex items-center gap-4">
              {/* Clear Chat Button */}
              {messages.length > 0 && (
                <button 
                  onClick={handleClearChat}
                  className="py-2 px-4 bg-red-50 text-red-600 border-2 border-red-200 rounded-full cursor-pointer font-bold text-sm tracking-wide transition-all hover:bg-red-100 hover:border-red-300 hover:shadow-md active:scale-[0.97] shadow-sm flex items-center gap-2"
                >
                  Clear Chat
                </button>
              )}

              {/* Language Toggle Button */}
              <button 
                onClick={() => setSelectedLanguage((prev) => prev === "English" ? "Bahasa Indonesia" : "English")}
                className="py-2 px-6 bg-blue-50 text-blue-700 border-2 border-blue-200 rounded-full cursor-pointer font-bold text-base tracking-wide transition-all hover:bg-blue-100 hover:border-blue-300 hover:shadow-md active:scale-[0.97] shadow-sm flex items-center gap-2"
              >
                Language: {selectedLanguage === "English" ? "English" : "Indonesian"}
              </button>
            </div>
          </div>

          {/* Messages Stream */}
          <div className="flex-1 p-5 overflow-y-auto flex flex-col gap-4">
            {messages.length === 0 && !isQuerying && (
              <div className="m-auto text-center text-slate-400 max-w-[400px] select-none">
                <div className="text-4xl mb-3.5"></div>
                <h4 className="m-0 mb-1.5 text-sm font-semibold text-slate-500">Grounded RAG Interface Online</h4>
                <p className="text-xs m-0 leading-relaxed text-slate-400">Ask standard maintenance procedures, troubleshooting codes, or threshold calibrations indexed from your engineering manuals.</p>
              </div>
            )}

            {messages.map((msg, index) => (
              <div key={index} style={{ display: 'flex', flexDirection: 'column', alignItems: msg.sender === 'user' ? 'flex-end' : 'flex-start' }}>
                
                {/* Bubble content */}
                {/* Bubble content */}
                <div style={{
                  maxWidth: '75%',
                  padding: '12px 16px',
                  borderRadius: '8px',
                  fontSize: '14px',
                  lineHeight: '1.5',
                  backgroundColor: msg.sender === 'user' ? '#2563eb' : msg.sender === 'system-error' ? '#fef2f2' : '#fff',
                  color: msg.sender === 'user' ? '#fff' : msg.sender === 'system-error' ? '#991b1b' : '#1e293b',
                  border: msg.sender === 'user' ? 'none' : `1px solid ${msg.sender === 'system-error' ? '#fca5a5' : '#e2e8f0'}`,
                  boxShadow: msg.sender === 'user' ? 'none' : '0 1px 2px rgba(0,0,0,0.05)',
                  // Remove 'pre-wrap' here so it doesn't conflict with Markdown's native HTML formatting
                }}>
                  {msg.sender === 'user' || msg.sender === 'system-error' ? (
                    <span style={{ whiteSpace: 'pre-wrap' }}>{msg.text}</span>
                  ) : (
                    <ReactMarkdown 
                        remarkPlugins={[remarkGfm]}
                        components={{
                          // Restore bullet points
                          ul: ({node, ...props}) => <ul style={{ listStyleType: 'disc', paddingLeft: '1.5rem', marginBottom: '1rem' }} {...props} />,
                          // Restore numbered lists
                          ol: ({node, ...props}) => <ol style={{ listStyleType: 'decimal', paddingLeft: '1.5rem', marginBottom: '1rem' }} {...props} />,
                          // Space out list items
                          li: ({node, ...props}) => <li style={{ marginBottom: '0.25rem' }} {...props} />,
                          // Space out paragraphs
                          p: ({node, ...props}) => <p style={{ marginBottom: '0.75rem' }} {...props} />,
                          // Format tables
                          table: ({node, ...props}) => <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '1rem', marginBottom: '1rem' }} {...props} />,
                          th: ({node, ...props}) => <th style={{ border: '1px solid #cbd5e1', padding: '8px 12px', backgroundColor: '#f8fafc', fontWeight: 'bold', textAlign: 'left' }} {...props} />,
                          td: ({node, ...props}) => <td style={{ border: '1px solid #cbd5e1', padding: '8px 12px', textAlign: 'left' }} {...props} />,
                          // Highlight safety warnings as red blocks
                          blockquote: ({node, ...props}) => (
                            <blockquote style={{ 
                              borderLeft: '4px solid #ef4444', 
                              backgroundColor: '#fef2f2', 
                              padding: '8px 16px', 
                              margin: '1rem 0', 
                              borderRadius: '0 4px 4px 0', 
                              color: '#991b1b', 
                              fontWeight: '500' 
                            }} {...props} />
                          )
                        }}
                      >
                        {msg.text}
                      </ReactMarkdown>
                  )}
                </div>

                {/* Grounding Metadata / Token Receipts for AI Responses */}
                {msg.sender === 'ai' && msg.metadata && (
                  <div style={{
                    marginTop: '6px',
                    padding: '8px 12px',
                    backgroundColor: '#f1f5f9',
                    border: '1px solid #cbd5e1',
                    borderRadius: '4px',
                    fontSize: '11px',
                    color: '#475569',
                    fontFamily: 'monospace',
                    display: 'flex',
                    gap: '15px'
                  }}>
                    <span>📊 <b>Prompt:</b> {msg.metadata.input_tokens}t</span>
                    <span><b>Generation:</b> {msg.metadata.output_tokens}t</span>
                    <span><b>Total:</b> {msg.metadata.total_tokens}t</span>
                  </div>
                )}
              </div>
            ))}

            {/* AI Generation Loader State */}
            {isQuerying && (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
                <div style={{
                  padding: '12px 16px',
                  backgroundColor: '#fff',
                  border: '1px solid #e2e8f0',
                  borderRadius: '8px',
                  fontSize: '13px',
                  color: '#64748b',
                  fontStyle: 'italic'
                }}>
                  Searching vector arrays and synthesizing responses...
                </div>
              </div>
            )}
            
            <div ref={chatBottomRef} />
          </div>

          {/* Lower Input Container Form */}
          <div style={{ padding: '15px 20px', backgroundColor: '#fff', borderTop: '1px solid #e2e8f0' }}>
            <form onSubmit={handleSendMessage} style={{ display: 'flex', gap: '10px' }}>
              <input
                type="text"
                value={inputQuery}
                onChange={(e) => setInputQuery(e.target.value)}
                placeholder="Ask an engineering or manual maintenance question..."
                disabled={isQuerying}
                style={{
                  flex: 1,
                  padding: '12px 15px',
                  border: '1px solid #cbd5e1',
                  borderRadius: '6px',
                  fontSize: '14px',
                  outline: 'none',
                  backgroundColor: isQuerying ? '#f8fafc' : '#fff'
                }}
              />
              <button
                type="submit"
                disabled={!inputQuery.trim() || isQuerying}
                style={{
                  padding: '0 20px',
                  backgroundColor: !inputQuery.trim() || isQuerying ? '#cbd5e1' : '#1e293b',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: !inputQuery.trim() || isQuerying ? 'not-allowed' : 'pointer',
                  fontWeight: 'bold',
                  fontSize: '14px'
                }}
              >
                Send
              </button>
            </form>
          </div>

        </main>
      </div>
    </div>
  );
};

export default SPMSChatDashboard;