import { useState } from 'react';
import { LoginPage } from './pages/LoginPage';
import { BoardPage } from './pages/BoardPage';

function App() {
  const [userEmail, setUserEmail] = useState<string | null>(null);

  if (!userEmail) {
    return <LoginPage onLogin={setUserEmail} />;
  }

  return (
    <BoardPage
      userEmail={userEmail}
      onLogout={() => setUserEmail(null)}
    />
  );
}

export default App;
