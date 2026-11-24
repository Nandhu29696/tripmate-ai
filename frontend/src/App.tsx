import { Route, Routes } from "react-router-dom";
import { FlashMessages, RedirectIfAuthed, RequireAuth } from "./components/RouteGuards";
import { AuthProvider } from "./context/AuthContext";
import { ToastProvider } from "./context/ToastContext";
import { TripsProvider } from "./context/TripsContext";
import { AppLayout } from "./layouts/AppLayout";
import { AuthLayout } from "./layouts/AuthLayout";
import { AccountPage } from "./pages/AccountPage";
import { ForgotPage } from "./pages/ForgotPage";
import { LoginPage } from "./pages/LoginPage";
import { NewTripPage } from "./pages/NewTripPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ResetPage } from "./pages/ResetPage";
import { TripPage } from "./pages/TripPage";

export function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <TripsProvider>
          <FlashMessages />
          <Routes>
            <Route element={<AuthLayout />}>
              <Route element={<RedirectIfAuthed />}>
                <Route path="/login" element={<LoginPage />} />
                <Route path="/forgot" element={<ForgotPage />} />
              </Route>
              {/* Reachable while signed in too: the emailed link works from any browser state. */}
              <Route path="/reset" element={<ResetPage />} />
            </Route>

            <Route element={<RequireAuth />}>
              <Route element={<AppLayout />}>
                <Route index element={<NewTripPage />} />
                <Route path="/trips/:threadId" element={<TripPage />} />
                <Route path="/account" element={<AccountPage />} />
              </Route>
            </Route>

            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </TripsProvider>
      </AuthProvider>
    </ToastProvider>
  );
}
