import { describe, expect, it, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render } from "@testing-library/react";
import { AuthProvider } from "../auth/AuthProvider";
import { LoginPage } from "./LoginPage";
import { clearTokens } from "../api/tokenStore";

function renderLogin() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/login"]}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<div>Register screen</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("LoginPage", () => {
  beforeEach(() => clearTokens());

  it("renders the sign-in form", async () => {
    renderLogin();
    expect(await screen.findByRole("heading", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("links to registration", async () => {
    renderLogin();
    await userEvent.click(await screen.findByRole("link", { name: /register/i }));
    expect(screen.getByText("Register screen")).toBeInTheDocument();
  });
});
