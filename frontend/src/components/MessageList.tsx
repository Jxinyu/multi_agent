import type { ChatMessage } from '../types';
import { MessageItem } from './MessageItem';

interface MessageListProps {
  messages: ChatMessage[];
}

export function MessageList({ messages }: MessageListProps) {
  return (
    <main className="message-list" aria-live="polite">
      {messages.map((message) => (
        <MessageItem key={message.id} message={message} />
      ))}
    </main>
  );
}
