import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

// --- API Configuration ---
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;
const WEBSOCKET_URL = import.meta.env.VITE_WEBSOCKET_URL;

// --- API Functions (Web-based) ---
const api = {
    startSession: async () => {
        const response = await fetch(`${API_BASE_URL}/api/v1/sessions/start`, { method: 'POST' });
        if (!response.ok) throw new Error('Failed to start a new session on the server.');
        return response.json();
    },
    uploadAudio: async (sessionId, audioBlob) => {
        const formData = new FormData();
        formData.append('audio_file', audioBlob, 'recording.wav');
        const response = await fetch(`${API_BASE_URL}/api/v1/sessions/upload-audio/${sessionId}`, {
            method: 'POST',
            body: formData,
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to upload audio file.');
        }
        return response.json();
    },
    checkFileReady: async (filePath) => {
        try {
            const response = await fetch(`${API_BASE_URL}${filePath}`, { method: 'HEAD' });
            return response.ok;
        } catch (error) {
            return false;
        }
    },
    sendEmail: async (to_email, pdf_path) => {
        const response = await fetch(`${API_BASE_URL}/api/v1/email/send`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ to_email, pdf_path }),
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to send email');
        }
        return response.json();
    }
};

// --- UI Components ---

const Loader = () => (
    <>
        <style>{`
            .loader {
                width: 50px;
                height: 50px;
                border-radius: 50%;
                animation: spin 1s linear infinite;
                margin: 0 auto;
                border: 4px solid #e2e8f0;
                border-top: 4px solid #9333ea;
            }
            html.dark .loader {
                border: 4px solid #4a5568;
                border-top: 4px solid #a855f7;
            }
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
        `}</style>
        <div className="loader"></div>
    </>
);

const EmailModal = ({ isOpen, onClose, onSend, pdfFile }) => {
    const [recipientEmail, setRecipientEmail] = useState('');
    const [isSending, setIsSending] = useState(false);
    const [error, setError] = useState('');

    const handleSendClick = async () => {
        setError('');
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(recipientEmail)) {
            setError("Please enter a valid email address.");
            return;
        }
        
        setIsSending(true);
        try {
            await onSend(recipientEmail, pdfFile);
            handleClose(); // Close modal on success
        } catch (e) {
            setError(e.message || 'An unknown error occurred.');
        } finally {
            setIsSending(false);
        }
    };
    
    const handleClose = () => {
        setRecipientEmail('');
        setError('');
        setIsSending(false);
        onClose();
    };

    return (
        <AnimatePresence>
            {isOpen && (
                <motion.div
                    initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                    className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4"
                    onClick={handleClose}
                >
                    <motion.div
                        initial={{ scale: 0.9, y: -20 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.9, y: -20 }}
                        className="bg-white dark:bg-slate-800 rounded-lg shadow-xl p-6 w-full max-w-md"
                        onClick={e => e.stopPropagation()}
                    >
                        <h2 className="text-xl font-bold text-slate-800 dark:text-white mb-4">Share Report via Email</h2>
                        <input
                            type="email" value={recipientEmail} onChange={(e) => setRecipientEmail(e.target.value)}
                            placeholder="name@example.com"
                            className="w-full p-2 rounded bg-slate-100 dark:bg-slate-700 border border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white focus:ring-2 focus:ring-purple-500"
                        />
                        {error && <p className="text-red-500 text-sm mt-2">{error}</p>}
                        <div className="flex justify-end gap-3 mt-6">
                            <button onClick={handleClose} className="px-4 py-2 rounded-lg bg-slate-200 hover:bg-slate-300 dark:bg-slate-600 dark:hover:bg-slate-500 font-semibold transition">Cancel</button>
                            <button onClick={handleSendClick} disabled={isSending} className="px-4 py-2 rounded-lg bg-purple-600 hover:bg-purple-700 text-white font-semibold transition disabled:bg-purple-400">
                                {isSending ? 'Sending...' : 'Send Email'}
                            </button>
                        </div>
                    </motion.div>
                </motion.div>
            )}
        </AnimatePresence>
    );
};


// --- View Components ---

const WelcomeScreen = () => (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }} className="text-center">
        <h2 className="text-3xl font-bold text-purple-600 dark:text-purple-400">Welcome to Notes Taker</h2>
        <p className="text-slate-600 dark:text-slate-400 mt-2">Press 'Start Recording' to begin.</p>
    </motion.div>
);

const RecordingView = ({ transcript }) => {
    const transcriptEndRef = useRef(null);
    useEffect(() => {
        transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [transcript]);

    return (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="w-full h-full flex flex-col space-y-4">
            <div className="flex-grow bg-slate-100 dark:bg-slate-800 p-4 rounded-lg border border-slate-200 dark:border-slate-700 overflow-y-auto">
                <h3 className="text-lg font-semibold text-purple-600 dark:text-purple-400 mb-2">Live Transcript</h3>
                {transcript.length > 0 ? (
                    transcript.map((line, i) => <p key={i} className="text-slate-800 dark:text-slate-300 mb-1">{line}</p>)
                ) : (
                    <p className="text-slate-500">Waiting for speech...</p>
                )}
                <div ref={transcriptEndRef} />
            </div>
        </motion.div>
    );
};


const ProcessingScreen = () => (
    <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} className="text-center space-y-4">
        <Loader />
        <h2 className="text-2xl font-semibold text-purple-600 dark:text-purple-300">Generating Your Scribe</h2>
        <p className="text-slate-500 dark:text-slate-400">This may take a moment. We're analyzing the audio and creating your report.</p>
    </motion.div>
);

// --- UPDATED: ResultsView with a working download handler ---
const ResultsView = ({ pdfFile, onReset, setAppError }) => {
    const [isEmailModalOpen, setIsEmailModalOpen] = useState(false);
    const [isDownloading, setIsDownloading] = useState(false);
    const fullPdfUrl = `${API_BASE_URL}${pdfFile}#toolbar=0&navpanes=0`;

    const handleSendEmail = async (recipientEmail, pdfPath) => {
        setAppError('');
        try {
            await api.sendEmail(recipientEmail, pdfPath);
            alert('Email sent successfully!');
        } catch (error) {
            setAppError(error.message || 'Could not send email.');
            throw error; // Re-throw to let the modal know
        }
    };

    // --- FIX: Implemented robust download logic ---
    const handleDownload = async () => {
        setIsDownloading(true);
        setAppError('');
        try {
            const response = await fetch(`${API_BASE_URL}${pdfFile}`);
            if (!response.ok) {
                throw new Error('Network response was not ok while downloading the file.');
            }
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            // Extract filename from the path
            a.download = pdfFile.split('/').pop() || 'meeting_report.pdf';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch (error) {
            console.error('Download failed:', error);
            setAppError('Could not download the file. Please try again.');
        } finally {
            setIsDownloading(false);
        }
    };

    return (
        <>
            <EmailModal isOpen={isEmailModalOpen} onClose={() => setIsEmailModalOpen(false)} onSend={handleSendEmail} pdfFile={pdfFile} />
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="w-full h-full flex flex-col">
                <h2 className="text-2xl font-bold text-purple-600 dark:text-purple-400 mb-4">Your Scribe is Ready</h2>
                <div className="flex-grow w-full h-96 border-2 border-slate-300 dark:border-slate-700 rounded-lg overflow-hidden mb-6">
                    <iframe src={fullPdfUrl} className="w-full h-full" title="PDF Preview" />
                </div>
                <div className="flex flex-col sm:flex-row justify-center items-center gap-4">
                    {/* Changed from <a> tag to <button> */}
                    <button onClick={handleDownload} disabled={isDownloading} className="w-full sm:w-auto text-center bg-blue-600 hover:bg-blue-700 text-white px-5 py-2 rounded-lg font-semibold transition-colors disabled:bg-blue-400">
                        {isDownloading ? 'Downloading...' : 'Download Report'}
                    </button>
                    <button onClick={() => setIsEmailModalOpen(true)} className="w-full sm:w-auto bg-purple-600 hover:bg-purple-700 text-white px-5 py-2 rounded-lg font-semibold transition-colors">Share via Email</button>
                    <button onClick={onReset} className="w-full sm:w-auto bg-slate-600 hover:bg-slate-700 text-white px-5 py-2 rounded-lg font-semibold transition-colors">New Recording</button>
                </div>
            </motion.div>
        </>
    );
};

// --- Layout Components ---

const Sidebar = ({ status, onStart, onStop, onReset, appError, theme, toggleTheme }) => {
    const [timer, setTimer] = useState(0);
    const isRecording = status === 'recording';

    useEffect(() => {
        let interval;
        if (isRecording) {
            interval = setInterval(() => setTimer(t => t + 1), 1000);
        } else {
            clearInterval(interval);
            setTimer(0);
        }
        return () => clearInterval(interval);
    }, [isRecording]);

    const formatTime = (seconds) => new Date(seconds * 1000).toISOString().substr(14, 5);
    const mainButtonText = status === 'idle' ? 'Start Recording' : 'Stop Recording';

    return (
        <aside className="w-full md:w-1/3 md:max-w-sm p-6 bg-slate-50 dark:bg-slate-800 flex flex-col space-y-6 border-r border-slate-200 dark:border-slate-700">
            <div className="flex justify-between items-center">
                <h1 className="text-3xl font-bold text-slate-800 dark:text-white">Notes Taker</h1>
                <button onClick={toggleTheme} className="p-2 rounded-full text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700">
                    {theme === 'dark' ? '☀️' : '🌙'}
                </button>
            </div>
            <div className="flex items-center space-x-2">
                <span className={`h-3 w-3 rounded-full ${isRecording ? 'bg-red-500 animate-pulse' : 'bg-green-500'}`}></span>
                <span className="text-slate-700 dark:text-slate-300 font-mono">
                    {isRecording ? `REC... ${formatTime(timer)}` : (status === 'processing' ? 'Processing...' : 'Ready')}
                </span>
            </div>
            {appError && (
                <div className="p-3 bg-red-100 dark:bg-red-900/50 border border-red-300 dark:border-red-700 rounded-lg text-red-700 dark:text-red-300 text-sm">
                    <strong>Error:</strong> {appError}
                </div>
            )}
            <div className="flex-grow flex items-end">
                {status === 'ready' ? (
                     <button onClick={onReset} className="w-full py-3 text-lg font-bold rounded-lg bg-purple-600 hover:bg-purple-700 text-white transition-all transform hover:scale-105">New Recording</button>
                ) : (
                    <button onClick={isRecording ? onStop : onStart} disabled={status === 'processing'} className={`w-full py-3 text-lg font-bold rounded-lg text-white transition-all transform hover:scale-105 ${isRecording ? 'bg-red-600 hover:bg-red-700' : 'bg-purple-600 hover:bg-purple-700'} ${status === 'processing' ? 'bg-slate-500 cursor-not-allowed' : ''}`}>
                        {status === 'processing' ? 'Processing...' : mainButtonText}
                    </button>
                )}
            </div>
        </aside>
    );
};

const MainContent = ({ status, transcript, pdfFile, onReset, setAppError, theme }) => (
    <main className="flex-1 p-4 md:p-8 flex items-center justify-center bg-white dark:bg-slate-900">
        <div className="w-full h-full max-w-4xl">
            <AnimatePresence mode="wait">
                <div key={status} className="w-full h-full flex items-center justify-center">
                    {status === 'idle' && <WelcomeScreen />}
                    {status === 'recording' && <RecordingView transcript={transcript} />}
                    {status === 'processing' && <ProcessingScreen />}
                    {status === 'ready' && <ResultsView pdfFile={pdfFile} onReset={onReset} setAppError={setAppError} />}
                </div>
            </AnimatePresence>
        </div>
    </main>
);

// --- Main App Component ---

export default function App() {
    const [status, setStatus] = useState('idle'); // idle, recording, processing, ready
    const [transcript, setTranscript] = useState([]);
    const [pdfFile, setPdfFile] = useState(null);
    const [appError, setAppError] = useState('');
    const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'light');

    // Refs for client-side recording & WebSocket
    const mediaRecorderRef = useRef(null);
    const audioChunksRef = useRef([]);
    const sessionIdRef = useRef(null);
    const socketRef = useRef(null);

    useEffect(() => {
        document.documentElement.classList.toggle('dark', theme === 'dark');
        localStorage.setItem('theme', theme);
    }, [theme]);

    const toggleTheme = () => setTheme(prev => prev === 'light' ? 'dark' : 'light');

    const handleStart = async () => {
        setAppError('');
        setPdfFile(null);
        setTranscript([]);
        setStatus('processing'); 
        
        try {
            const sessionData = await api.startSession();
            sessionIdRef.current = sessionData.session_id;

            socketRef.current = new WebSocket(`${WEBSOCKET_URL}/ws/live/${sessionIdRef.current}`);
            socketRef.current.onopen = () => console.log('WebSocket connected');
            socketRef.current.onclose = () => console.log('WebSocket disconnected');
            socketRef.current.onmessage = (event) => {
                setTranscript(prev => [...prev, event.data]);
            };

            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

            mediaRecorderRef.current = new MediaRecorder(stream);
            mediaRecorderRef.current.ondataavailable = event => {
                if (event.data.size > 0) {
                    audioChunksRef.current.push(event.data);
                    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
                        socketRef.current.send(event.data);
                    }
                }
            };
            mediaRecorderRef.current.onstop = handleUpload;

            mediaRecorderRef.current.start(2000); 
            setStatus('recording');

        } catch (error) {
            console.error("Failed to start recording:", error);
            setAppError(error.message || 'Microphone access denied.');
            setStatus('idle');
        }
    };

    const handleStop = () => {
        if (mediaRecorderRef.current && status === 'recording') {
            mediaRecorderRef.current.stop();
            mediaRecorderRef.current.stream.getTracks().forEach(track => track.stop());
            if (socketRef.current) {
                socketRef.current.close();
            }
            setStatus('processing');
        }
    };

    const handleUpload = async () => {
        if (audioChunksRef.current.length === 0) return;

        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        audioChunksRef.current = [];

        try {
            const result = await api.uploadAudio(sessionIdRef.current, audioBlob);
            const expectedPdfPath = result.pdf_url;
            
            const pollForFile = async (retries = 30) => {
                if (retries <= 0) throw new Error("Processing timed out.");
                const isReady = await api.checkFileReady(expectedPdfPath);
                if (isReady) {
                    setPdfFile(expectedPdfPath);
                    setStatus('ready');
                } else {
                    setTimeout(() => pollForFile(retries - 1), 3000);
                }
            };
            await pollForFile();

        } catch (error) {
            console.error("Failed to upload or process recording:", error);
            setAppError(error.message || 'Could not process the recording.');
            setStatus('idle');
        }
    };

    const handleReset = () => {
        setAppError('');
        setStatus('idle');
        setPdfFile(null);
        setTranscript([]);
    };

    return (
        <div className="min-h-screen flex flex-col md:flex-row font-sans text-slate-900 dark:text-slate-200 bg-white dark:bg-slate-900">
            <Sidebar status={status} onStart={handleStart} onStop={handleStop} onReset={handleReset} appError={appError} theme={theme} toggleTheme={toggleTheme} />
            <MainContent status={status} transcript={transcript} pdfFile={pdfFile} onReset={handleReset} setAppError={setAppError} theme={theme} />
        </div>
    );
}
