import { useEffect, useState } from "react";
import { api } from "../../api/client";

export type SetupStatus = {
  needs_setup: boolean;
  signup_enabled: boolean;
  email_enabled: boolean;
};

/** Public install status: whether the first (admin) account still has to be created. */
export function useSetupStatus(): SetupStatus | null {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  useEffect(() => {
    let cancelled = false;
    api<SetupStatus>("/auth/setup")
      .then((value) => { if (!cancelled) setStatus(value); })
      .catch(() => {
        if (!cancelled) setStatus({ needs_setup: false, signup_enabled: true, email_enabled: true });
      });
    return () => { cancelled = true; };
  }, []);
  return status;
}
