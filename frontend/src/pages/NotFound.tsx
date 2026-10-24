import { Link } from "react-router-dom";
import { EmptyState } from "../components/ui";

export default function NotFound() {
  return (
    <div className="mx-auto mt-16 max-w-md px-4">
      <EmptyState title="Page not found">
        <Link className="font-semibold text-indigo-800 underline" to="/">
          Go to the start page
        </Link>
      </EmptyState>
    </div>
  );
}
