import { LibraryBig } from "lucide-react";
import type { ApiError } from "../lib/api";

export function SignOutForm({ className }: { className?: string }) {
  return (
    <form method="post" action="/auth/signout" className={className}>
      <button type="submit" className="signout">
        Sign out
      </button>
    </form>
  );
}

/** Full-screen gate shown when the library answers 401, 403, or 503. */
export function AuthScreen({ error }: { error: ApiError }) {
  const signInUrl =
    typeof error.body.sign_in_url === "string" ? error.body.sign_in_url : "/auth/signin?returnTo=/";
  return (
    <main className="gate">
      <div className="gatecard">
        <div className="brand">
          <LibraryBig size={30} />
          Shelfmark
        </div>
        <p className="deskname">A keyboard-first personal reading desk.</p>
        {error.status === 401 ? (
          <a className="primary" href={signInUrl}>
            Sign in
          </a>
        ) : (
          <>
            <p className="gatedetail">{error.detail}</p>
            {error.status === 403 && <SignOutForm />}
          </>
        )}
      </div>
    </main>
  );
}
