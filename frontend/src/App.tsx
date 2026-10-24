import { Navigate, Route, Routes } from "react-router-dom";
import { homeFor, useAuth } from "./auth/AuthContext";
import { RequireRole } from "./auth/RequireRole";
import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
import Applications from "./pages/candidate/Applications";
import Assessments from "./pages/candidate/Assessments";
import Interviews from "./pages/candidate/Interviews";
import JobDetail from "./pages/candidate/JobDetail";
import Jobs from "./pages/candidate/Jobs";
import Profile from "./pages/candidate/Profile";
import TakeAssessment from "./pages/candidate/TakeAssessment";
import Login from "./pages/Login";
import NotFound from "./pages/NotFound";
import Register from "./pages/Register";

function Start() {
  const { status, user } = useAuth();
  if (status === "loading") return <Spinner label="Loading…" />;
  return <Navigate to={user ? homeFor(user.role) : "/login"} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Start />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />

      <Route element={<RequireRole role="candidate" />}>
        <Route element={<Layout />}>
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/jobs/:id" element={<JobDetail />} />
          <Route path="/applications" element={<Applications />} />
          <Route path="/profile" element={<Profile />} />
          <Route path="/assessments" element={<Assessments />} />
          <Route path="/assessments/take/:attemptId" element={<TakeAssessment />} />
          <Route path="/interviews" element={<Interviews />} />
        </Route>
      </Route>

      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
