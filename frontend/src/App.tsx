import { useEffect, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { LoginPage } from './pages/LoginPage';
import { BoardPage } from './pages/BoardPage';
import {
  SESSION_EXPIRED_EVENT,
  clearSession,
  getAccessToken,
  getStoredEmail,
} from './lib/api';
import { logoutUser } from './lib/auth';

function LoginRoute({ onLogin }: { onLogin: (email: string) => void }) {
  const navigate = useNavigate();
  return (
    <LoginPage
      onLogin={(email) => {
        onLogin(email);
        navigate('/dashboard', { replace: true });
      }}
    />
  );
}

function App() {
  const [userEmail, setUserEmail] = useState<string | null>(() => {
    const email = getStoredEmail();
    const token = getAccessToken();
    return email && token ? email : null;
  });

  // The API layer clears the stored token on any 401 and announces it here.
  useEffect(() => {
    const onExpired = () => setUserEmail(null);
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, []);

  const handleLogin = (email: string) => {
    setUserEmail(email);
  };

  const handleLogout = async () => {
    await logoutUser();
    clearSession();
    setUserEmail(null);
  };

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/login"
          element={
            userEmail ? (
              <Navigate to="/dashboard" replace />
            ) : (
              <LoginRoute onLogin={handleLogin} />
            )
          }
        />
        <Route
          path="/dashboard"
          element={
            userEmail ? (
              <BoardPage userEmail={userEmail} onLogout={handleLogout} />
            ) : (
              <Navigate to="/login" replace />
            )
          }
        />
        <Route
          path="*"
          element={<Navigate to={userEmail ? '/dashboard' : '/login'} replace />}
        />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
