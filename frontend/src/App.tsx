import { Navigate, Route, Routes, useNavigate } from 'react-router-dom';

import { AuthState } from './components/AuthState';
import { ProductShell } from './layouts/ProductShell';
import { LoginPage } from './pages/auth/LoginPage';
import { AdminModelsPage } from './pages/admin/AdminModelsPage';
import { AdminOperationsPage } from './pages/admin/AdminOperationsPage';
import { AdminSecurityPage } from './pages/admin/AdminSecurityPage';
import { AdminSettingsPage } from './pages/admin/AdminSettingsPage';
import { AdminTenantsPage } from './pages/admin/AdminTenantsPage';
import { EnterpriseAgentsPage } from './pages/enterprise/EnterpriseAgentsPage';
import { EnterpriseEvaluationPage } from './pages/enterprise/EnterpriseEvaluationPage';
import { EnterpriseKnowledgePage } from './pages/enterprise/EnterpriseKnowledgePage';
import { EnterpriseMembersPage } from './pages/enterprise/EnterpriseMembersPage';
import { EnterpriseOverviewPage } from './pages/enterprise/EnterpriseOverviewPage';
import { AgentAnswerPage } from './pages/user/AgentAnswerPage';
import { EnterpriseSearchPage } from './pages/user/EnterpriseSearchPage';
import { UserWorkbenchPage } from './pages/user/UserWorkbenchPage';
import { UserDocumentsPage } from './pages/user/UserDocumentsPage';
import { UserTasksPage } from './pages/user/UserTasksPage';
import { useAuth } from './hooks/useAuth';
import { useChatSession } from './hooks/useChatSession';
import { useCurrentUser } from './hooks/useCurrentUser';

function AuthenticatedApp() {
  const navigate = useNavigate();
  const chat = useChatSession();
  const currentUser = useCurrentUser();

  const sendFromWorkbench = async (query: string) => {
    navigate(`/app/chat/${chat.session.threadId}`);
    await chat.send(query);
  };

  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/app" replace />} />

      <Route element={<ProductShell mode="user" currentUser={currentUser.user} />}>
        <Route
          path="/app"
          element={(
            <UserWorkbenchPage
              session={chat.session}
              history={chat.history}
              attachments={chat.attachments}
              onSend={sendFromWorkbench}
              onStop={chat.stop}
              onAddAttachments={chat.addAttachments}
              onRemoveAttachment={chat.removeAttachment}
              onResume={(threadId) => {
                chat.resumeSession(threadId);
                navigate(`/app/chat/${threadId}`);
              }}
            />
          )}
        />
        <Route
          path="/app/chat/:threadId"
          element={(
            <AgentAnswerPage
              session={chat.session}
              attachments={chat.attachments}
              onSend={chat.send}
              onStop={chat.stop}
              onAddAttachments={chat.addAttachments}
              onRemoveAttachment={chat.removeAttachment}
            />
          )}
        />
        <Route path="/app/search" element={<EnterpriseSearchPage />} />
        <Route path="/app/tasks" element={<UserTasksPage />} />
        <Route path="/app/documents" element={<UserDocumentsPage />} />
      </Route>

      <Route element={<ProductShell mode="enterprise" currentUser={currentUser.user} />}>
        <Route path="/enterprise" element={<EnterpriseOverviewPage />} />
        <Route path="/enterprise/knowledge" element={<EnterpriseKnowledgePage />} />
        <Route path="/enterprise/agents" element={<EnterpriseAgentsPage />} />
        <Route path="/enterprise/members" element={<EnterpriseMembersPage />} />
        <Route path="/enterprise/evaluation" element={<EnterpriseEvaluationPage />} />
      </Route>

      <Route element={<ProductShell mode="admin" currentUser={currentUser.user} />}>
        <Route path="/admin" element={<Navigate to="/admin/tenants" replace />} />
        <Route path="/admin/tenants" element={<AdminTenantsPage />} />
        <Route path="/admin/security" element={<AdminSecurityPage />} />
        <Route path="/admin/operations" element={<AdminOperationsPage />} />
        <Route path="/admin/models" element={<AdminModelsPage />} />
        <Route path="/admin/settings" element={<AdminSettingsPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/app" replace />} />
    </Routes>
  );
}

function AppContent() {
  const auth = useAuth();

  if (auth.status === 'initializing') {
    return <AuthState auth={auth} onRetry={auth.retryDevelopmentAuth} />;
  }

  if (auth.status !== 'authenticated') {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage error={auth.error} onRetry={auth.retryDevelopmentAuth} />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return <AuthenticatedApp />;
}

export default function App() {
  return <AppContent />;
}
