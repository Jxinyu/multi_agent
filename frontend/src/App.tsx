import { useEffect } from 'react';
import { Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom';

import { AuthState } from './components/AuthState';
import { ProductShell } from './layouts/ProductShell';
import { LoginPage } from './pages/auth/LoginPage';
import { AdminModelsPage } from './pages/admin/AdminModelsPage';
import { AdminOperationsPage } from './pages/admin/AdminOperationsPage';
import { AdminSecurityPage } from './pages/admin/AdminSecurityPage';
import { AdminAuditEventDetailPage } from './pages/admin/AdminAuditEventDetailPage';
import { AdminSettingsPage } from './pages/admin/AdminSettingsPage';
import { AdminTenantsPage } from './pages/admin/AdminTenantsPage';
import { AdminTenantDetailPage } from './pages/admin/AdminTenantDetailPage';
import { AdminServiceDetailPage } from './pages/admin/AdminServiceDetailPage';
import { EnterpriseAgentsPage } from './pages/enterprise/EnterpriseAgentsPage';
import { EnterpriseAgentDetailPage } from './pages/enterprise/EnterpriseAgentDetailPage';
import { EnterpriseEvaluationPage } from './pages/enterprise/EnterpriseEvaluationPage';
import { EnterpriseEvaluationRunPage } from './pages/enterprise/EnterpriseEvaluationRunPage';
import { EnterpriseKnowledgePage } from './pages/enterprise/EnterpriseKnowledgePage';
import { EnterpriseMembersPage } from './pages/enterprise/EnterpriseMembersPage';
import { EnterpriseMemberDetailPage } from './pages/enterprise/EnterpriseMemberDetailPage';
import { EnterpriseOverviewPage } from './pages/enterprise/EnterpriseOverviewPage';
import { HelpCenterPage } from './pages/shared/HelpCenterPage';
import { NotificationCenterPage } from './pages/shared/NotificationCenterPage';
import { ProfilePage } from './pages/shared/ProfilePage';
import { AgentAnswerPage } from './pages/user/AgentAnswerPage';
import { EnterpriseSearchPage } from './pages/user/EnterpriseSearchPage';
import { SearchEvidenceDetailPage } from './pages/user/SearchEvidenceDetailPage';
import { UserWorkbenchPage } from './pages/user/UserWorkbenchPage';
import { DocumentDetailPage } from './pages/user/DocumentDetailPage';
import { UserDocumentsPage } from './pages/user/UserDocumentsPage';
import { UserTaskDetailPage } from './pages/user/UserTaskDetailPage';
import { UserTasksPage } from './pages/user/UserTasksPage';
import { useAuth } from './hooks/useAuth';
import { useChatSession } from './hooks/useChatSession';
import { useCurrentUser } from './hooks/useCurrentUser';

type ChatController = ReturnType<typeof useChatSession>;

function AgentAnswerRoute({ chat }: { chat: ChatController }) {
  const { threadId } = useParams();
  useEffect(() => {
    if (threadId && threadId !== chat.session.threadId) {
      void chat.loadSession(threadId).catch(() => undefined);
    }
  }, [threadId]);
  return (
    <AgentAnswerPage
      session={chat.session}
      attachments={chat.attachments}
      onSend={chat.send}
      onStop={chat.stop}
      onAddAttachments={chat.addAttachments}
      onRemoveAttachment={chat.removeAttachment}
    />
  );
}

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
          element={<AgentAnswerRoute chat={chat} />}
        />
        <Route path="/app/search" element={<EnterpriseSearchPage />} />
        <Route path="/app/search/evidence/:evidenceId" element={<SearchEvidenceDetailPage />} />
        <Route path="/app/tasks" element={<UserTasksPage />} />
        <Route path="/app/tasks/:taskId" element={<UserTaskDetailPage />} />
        <Route path="/app/documents" element={<UserDocumentsPage />} />
        <Route path="/app/documents/:documentId" element={<DocumentDetailPage mode="user" />} />
        <Route path="/app/notifications" element={<NotificationCenterPage mode="user" />} />
        <Route path="/app/help" element={<HelpCenterPage mode="user" />} />
        <Route path="/app/profile" element={<ProfilePage mode="user" currentUser={currentUser.user} />} />
      </Route>

      <Route element={<ProductShell mode="enterprise" currentUser={currentUser.user} />}>
        <Route path="/enterprise" element={<EnterpriseOverviewPage />} />
        <Route path="/enterprise/knowledge" element={<EnterpriseKnowledgePage />} />
        <Route path="/enterprise/knowledge/:documentId" element={<DocumentDetailPage mode="enterprise" />} />
        <Route path="/enterprise/agents" element={<EnterpriseAgentsPage />} />
        <Route path="/enterprise/agents/:agentId" element={<EnterpriseAgentDetailPage />} />
        <Route path="/enterprise/members" element={<EnterpriseMembersPage />} />
        <Route path="/enterprise/members/:actorId" element={<EnterpriseMemberDetailPage />} />
        <Route path="/enterprise/evaluation" element={<EnterpriseEvaluationPage />} />
        <Route path="/enterprise/evaluation/:runId" element={<EnterpriseEvaluationRunPage />} />
        <Route path="/enterprise/notifications" element={<NotificationCenterPage mode="enterprise" />} />
        <Route path="/enterprise/help" element={<HelpCenterPage mode="enterprise" />} />
        <Route path="/enterprise/profile" element={<ProfilePage mode="enterprise" currentUser={currentUser.user} />} />
      </Route>

      <Route element={<ProductShell mode="admin" currentUser={currentUser.user} />}>
        <Route path="/admin" element={<Navigate to="/admin/tenants" replace />} />
        <Route path="/admin/tenants" element={<AdminTenantsPage />} />
        <Route path="/admin/tenants/:tenantId" element={<AdminTenantDetailPage />} />
        <Route path="/admin/security" element={<AdminSecurityPage />} />
        <Route path="/admin/security/:eventId" element={<AdminAuditEventDetailPage />} />
        <Route path="/admin/operations" element={<AdminOperationsPage />} />
        <Route path="/admin/operations/services/:serviceName" element={<AdminServiceDetailPage />} />
        <Route path="/admin/models" element={<AdminModelsPage />} />
        <Route path="/admin/settings" element={<AdminSettingsPage />} />
        <Route path="/admin/notifications" element={<NotificationCenterPage mode="admin" />} />
        <Route path="/admin/help" element={<HelpCenterPage mode="admin" />} />
        <Route path="/admin/profile" element={<ProfilePage mode="admin" currentUser={currentUser.user} />} />
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
