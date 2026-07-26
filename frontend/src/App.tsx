import { useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { LoginPage } from './pages/LoginPage';
import { BoardPage } from './pages/BoardPage';
import {
  clearSession,
  getAccessToken,
  getStoredEmail,
  getStoredUsername,
} from './lib/api';
import { logoutUser } from './lib/auth';

interface AuthUser {
  email: string;
  username: string;
}

function LoginRoute({ onLogin }: { onLogin: (user: AuthUser) => void }) {
  const navigate = useNavigate();
  return (
    <LoginPage
      onLogin={(user) => {
        onLogin(user);
        navigate('/dashboard', { replace: true });
      }}
    />
  );
}

function App() {
  const [user, setUser] = useState<AuthUser | null>(() => {
    const email = getStoredEmail();
    const token = getAccessToken();
    if (!email || !token) return null;
    return { email, username: getStoredUsername() || email.split('@')[0] };
  });

  const handleLogout = async () => {
    await logoutUser();
    clearSession();
    setUser(null);
  };

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/login"
          element={
            user ? (
              <Navigate to="/dashboard" replace />
            ) : (
              <LoginRoute onLogin={setUser} />
            )
          }
        />
        <Route
          path="/dashboard"
          element={
            user ? (
              <BoardPage
                userEmail={user.email}
                username={user.username}
                onLogout={handleLogout}
              />
            ) : (
              <Navigate to="/login" replace />
            )
          }
        />
        <Route
          path="*"
          element={<Navigate to={user ? '/dashboard' : '/login'} replace />}
        />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
