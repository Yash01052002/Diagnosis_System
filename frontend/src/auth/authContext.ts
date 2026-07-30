import { createContext } from "react";
import type { RoleName, User } from "../api/types";

export interface AuthState {
  user: User | null;
  /** True until the initial "am I logged in?" check resolves. */
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: (allSessions?: boolean) => Promise<void>;
  /** Replace the cached user after a profile edit. */
  setUser: (user: User) => void;
  hasRole: (...roles: RoleName[]) => boolean;
  isAdmin: boolean;
  isEngineer: boolean;
}

export const AuthContext = createContext<AuthState | null>(null);
