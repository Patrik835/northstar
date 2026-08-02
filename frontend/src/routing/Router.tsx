import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type AnchorHTMLAttributes,
  type MouseEvent,
  type ReactNode,
} from "react";

type RouterValue = {
  path: string;
  navigate: (path: string, replace?: boolean) => void;
};

const RouterContext = createContext<RouterValue | null>(null);

export function RouterProvider({ children }: { children: ReactNode }) {
  const [path, setPath] = useState(window.location.pathname);

  useEffect(() => {
    const onPopState = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = useCallback((nextPath: string, replace = false) => {
    window.history[replace ? "replaceState" : "pushState"]({}, "", nextPath);
    setPath(new URL(nextPath, window.location.origin).pathname);
  }, []);

  const value = useMemo(() => ({ path, navigate }), [path, navigate]);
  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;
}

export function useRouter() {
  const value = useContext(RouterContext);
  if (!value) throw new Error("useRouter must be used inside RouterProvider");
  return value;
}

type LinkProps = AnchorHTMLAttributes<HTMLAnchorElement> & {
  to: string;
  active?: boolean;
};

export function Link({ to, active, onClick, className, ...props }: LinkProps) {
  const { navigate } = useRouter();
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event);
    if (
      !event.defaultPrevented &&
      event.button === 0 &&
      !event.metaKey &&
      !event.ctrlKey &&
      !event.shiftKey &&
      !event.altKey
    ) {
      event.preventDefault();
      navigate(to);
    }
  }
  return (
    <a
      href={to}
      className={[className, active ? "active" : ""].filter(Boolean).join(" ")}
      onClick={follow}
      {...props}
    />
  );
}
