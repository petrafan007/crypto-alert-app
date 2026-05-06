import React, { createContext, useContext, useState, useEffect } from 'react';
import axios from 'axios';

const AuthContext = createContext();

// Global logout state - make it accessible globally
window.globalIsLoggingOut = false;

// Create a single axios interceptor that persists
const requestInterceptor = axios.interceptors.request.use(
  (config) => {
    if (window.globalIsLoggingOut) {
      // Cancel the request if we're logging out
      const error = new Error('Request cancelled - logging out');
      error.isCanceled = true;
      return Promise.reject(error);
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

export function useAuth() {
  return useContext(AuthContext);
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [isLoggingOut, setIsLoggingOut] = useState(false);


  // Check if user is logged in on app start, but only if a session cookie is present
  useEffect(() => {
    // Check if we're in logout state first
    if (window.globalIsLoggingOut) {
      setUser(null);
      setLoading(false);
      return;
    }

    // Check if we're on the login page - if so, don't auto-check auth
    if (window.location.pathname === '/login') {
      setUser(null);
      setLoading(false);
      return;
    }

    // Only check auth if a session cookie exists
    if (document.cookie.includes('session') || document.cookie.includes('sessionid') || document.cookie.includes('flask_session')) {
      checkAuthStatus();
    } else {
      setUser(null);
      setLoading(false);
    }
  }, []);

  const checkAuthStatus = async () => {
    try {
      if (isLoggingOut || window.globalIsLoggingOut) {
        setLoading(false);
        return;
      }
      if (user && user.id) {
        setLoading(false);
        return;
      }
      // Try to access a protected endpoint to check auth status and get user info
      const response = await axios.get('/api/coin-data');
      // If response has user info, set it
      if (response.data && response.data.user_id && response.data.username) {
        setUser({
          id: response.data.user_id,
          username: response.data.username,
          isAuthenticated: true
        });
      } else {
        setUser({ isAuthenticated: true });
      }
    } catch (error) {
      // Only log error if not 401 (unauthenticated)
      if (error.response && error.response.status !== 401) {
        console.error('Auth check error:', error);
      }
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  const login = async (username, password) => {
    try {
      // Reset logout flags
      window.globalIsLoggingOut = false;

      // Use JSON for API login
      const response = await axios.post('/api/login', {
        username,
        password
      }, {
        withCredentials: true
      });

      // If login successful, set user from response
      if (response.data && response.data.user_id && response.data.username) {
        setUser({
          id: response.data.user_id,
          username: response.data.username,
          isAuthenticated: true
        });
      } else {
        await checkAuthStatus();
      }
      return { success: true };
    } catch (error) {
      console.error('Login error:', error);
      return {
        success: false,
        error: error.response?.data?.error || 'Login failed'
      };
    }
  };

  const logout = async () => {
    // Set global logout flag FIRST
    window.globalIsLoggingOut = true;

    // Clear user state
    setUser(null);
    setIsLoggingOut(true);

    // Clear all intervals and timeouts
    const highestTimeoutId = setTimeout(";");
    for (let i = 0; i < highestTimeoutId; i++) {
      clearTimeout(i);
    }

    const highestIntervalId = setInterval(";");
    for (let i = 0; i < highestIntervalId; i++) {
      clearInterval(i);
    }

    // Clear localStorage and sessionStorage
    try {
      localStorage.clear();
      sessionStorage.clear();
    } catch (error) {
      // Ignore storage errors
    }

    // Server-side logout (API)
    try {
      await fetch('/api/logout', {
        method: 'POST',
        credentials: 'include'
      });
    } catch (error) {
      // Ignore any errors
    }

    // Proactively clear cookies in browser scope
    try {
      const cookies = document.cookie.split(';');
      for (const c of cookies) {
        const eqPos = c.indexOf('=');
        const name = eqPos > -1 ? c.substr(0, eqPos).trim() : c.trim();
        document.cookie = `${name}=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;`;
        document.cookie = `${name}=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain=${window.location.hostname};`;
        document.cookie = `${name}=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain=.${window.location.hostname};`;
      }
    } catch { }

    // Add a delay to ensure logout is processed
    setTimeout(() => {
      // Force immediate redirect with cache busting and clear any auth state
      window.globalIsLoggingOut = false; // Reset the flag
      window.location.href = '/login?' + Date.now();
    }, 200);
  };

  const value = {
    user,
    login,
    logout,
    loading,
    isLoggingOut,
    checkAuthStatus // Exporting this so Signup.jsx can use it
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
} 