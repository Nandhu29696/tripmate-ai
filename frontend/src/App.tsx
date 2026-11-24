import { Route, Routes } from "react-router-dom";
import { FlashMessages, RedirectIfAuthed, RequireAdmin, RequireAuth } from "./components/RouteGuards";
import { AuthProvider } from "./context/AuthContext";
import { ToastProvider } from "./context/ToastContext";
import { TripsProvider } from "./context/TripsContext";
import { AppLayout } from "./layouts/AppLayout";
import { AuthLayout } from "./layouts/AuthLayout";
import { AccountPage } from "./pages/AccountPage";
import { AdminLayout } from "./pages/admin/AdminLayout";
import { LogsTab } from "./pages/admin/LogsTab";
import { OverviewTab } from "./pages/admin/OverviewTab";
import { SystemTab } from "./pages/admin/SystemTab";
import { TripsTab } from "./pages/admin/TripsTab";
import { UsersTab } from "./pages/admin/UsersTab";
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
                <Route element={<RequireAdmin />}>
                  <Route path="/admin" element={<AdminLayout />}>
                    <Route index element={<OverviewTab />} />
                    <Route path="users" element={<UsersTab />} />
                    <Route path="trips" element={<TripsTab />} />
                    <Route path="logs" element={<LogsTab />} />
                    <Route path="system" element={<SystemTab />} />
                  </Route>
                </Route>
              </Route>
            </Route>

            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </TripsProvider>
      </AuthProvider>
    </ToastProvider>
  );
}
