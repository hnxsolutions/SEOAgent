'use client';

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface AuthState {
  user: {
    id: string;
    email: string;
    full_name?: string;
  } | null;
  accessToken: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;
  login: (_accessToken: string, _refreshToken: string) => void;
  logout: () => void;
  setUser: (_user: { id: string; email: string; full_name?: string }) => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
      login: (accessToken, refreshToken) => {
        localStorage.setItem('access_token', accessToken);
        set({
          accessToken,
          refreshToken,
          isAuthenticated: true,
        });
      },
      logout: () => {
        localStorage.removeItem('access_token');
        set({
          user: null,
          accessToken: null,
          refreshToken: null,
          isAuthenticated: false,
        });
      },
      setUser: (user) => set({ user }),
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
);
