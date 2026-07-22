import { useState } from 'react';
import { Sidebar } from './components/layout/Sidebar';
import { TopBar } from './components/layout/TopBar';
import { ChatPanel } from './components/chat/ChatPanel';
import { DashboardCanvas } from './components/canvas/DashboardCanvas';
import { useDashboard } from './hooks/useDashboard';
import type { SidebarItemId } from './types/dashboard';
import './App.css';

function App() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);
  const [activeItem, setActiveItem] = useState<SidebarItemId | null>('ai-chat');

  const {
    dashboard,
    messages,
    isThinking,
    selectWidget,
    updateWidget,
    deleteWidget,
    sendMessage,
  } = useDashboard();

  const handleSidebarSelect = (id: SidebarItemId) => {
    setActiveItem(id);
    if (id === 'ai-chat') {
      setChatOpen(true);
    }
  };

  return (
    <div className="board-app">
      <TopBar
        title="Untitled dashboard"
        sidebarCollapsed={sidebarCollapsed}
        chatOpen={chatOpen}
        widgetCount={dashboard.widgets.length}
        onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
        onToggleChat={() => {
          setChatOpen((v) => {
            const next = !v;
            if (next) setActiveItem('ai-chat');
            return next;
          });
        }}
      />

      <div className="board-body">
        <Sidebar
          collapsed={sidebarCollapsed}
          activeItem={activeItem}
          onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
          onSelect={handleSidebarSelect}
        />

        <ChatPanel
          open={chatOpen}
          messages={messages}
          isThinking={isThinking}
          onClose={() => setChatOpen(false)}
          onSend={sendMessage}
          onFocusChart={(chartId) => selectWidget(chartId)}
        />

        <DashboardCanvas
          widgets={dashboard.widgets}
          selectedWidgetId={dashboard.selectedWidgetId}
          onSelect={selectWidget}
          onUpdate={updateWidget}
          onDelete={deleteWidget}
        />
      </div>
    </div>
  );
}

export default App;
