import { useEffect, useRef } from 'react';
import axios from 'axios';

// Polls /api/notifications and calls onNewNotification for each new notification
export default function useNotificationPoller(userId, onNewNotification) {
  const lastSeenId = useRef(null);

  useEffect(() => {
    if (!userId) return;
    let interval;
    let isMounted = true;

    async function poll() {
      try {
        // Always include credentials for auth
        const res = await axios.get('/api/notifications', { withCredentials: true });
        if (!isMounted) return;
        const notifications = res.data || [];
        if (notifications.length === 0) return;
        // Find the latest notification
        const latest = notifications[notifications.length - 1];
        if (lastSeenId.current !== latest.id) {
          // Only fire for new notifications
          if (lastSeenId.current !== null) {
            onNewNotification(latest);
          }
          lastSeenId.current = latest.id;
        }
      } catch (e) {
        // Ignore errors
      }
    }
    poll();
    interval = setInterval(poll, 5000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [userId, onNewNotification]);
}
