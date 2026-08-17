import { useEffect, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { LoginPage } from './pages/LoginPage';
import { BoardPage } from './pages/BoardPage';
import { OAuthCallbackPage } from './pages/OAuthCallbackPage';
import { ResetPasswordPage } from './pages/ResetPasswordPage';
import { SettingsPage } from './pages/SettingsPage';
import { SharedBoardPage } from './pages/SharedBoardPage';
import {
  SESSION_EXPIRED_EVENT,
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

function DashboardRoute({
  user,
  onLogout,
}: {
  user: AuthUser;
  onLogout: () => void | Promise<void>;
}) {
  const navigate = useNavigate();
  return (
    <BoardPage
      userEmail={user.email}
      username={user.username}
      onLogout={async () => {
        await onLogout();
        navigate('/login', { replace: true });
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

  useEffect(() => {
    const onExpired = () => setUser(null);
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, []);

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
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route
          path="/oauth/callback"
          element={<OAuthCallbackPage onLogin={setUser} />}
        />
        <Route
          path="/dashboard"
          element={
            user ? (
              <DashboardRoute user={user} onLogout={handleLogout} />
            ) : (
              <Navigate to="/login" replace />
            )
          }
        />
        <Route
          path="/dashboard/:dashboardId"
          element={
            user ? (
              <DashboardRoute user={user} onLogout={handleLogout} />
            ) : (
              <Navigate to="/login" replace />
            )
          }
        />
        <Route
          path="/settings"
          element={
            user ? (
              <SettingsPage userEmail={user.email} username={user.username} />
            ) : (
              <Navigate to="/login" replace />
            )
          }
        />
        <Route path="/shared/:dashboardId" element={<SharedBoardPage />} />
        <Route
          path="*"
          element={<Navigate to={user ? '/dashboard' : '/login'} replace />}
        />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
