import { useCallback, useEffect, useRef, useState } from "react";

interface State<T> {
  data: T | undefined;
  error: string | undefined;
  loading: boolean;
  /** True on a refetch that already has data -- render the old view dimmed. */
  refreshing: boolean;
}

/**
 * Fetch-on-mount with a manual `reload`.
 *
 * Deliberately keeps the previous `data` while refetching so the UI dims
 * instead of collapsing to a skeleton and jumping the layout.
 */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[]): State<T> & {
  reload: () => void;
} {
  const [state, setState] = useState<State<T>>({
    data: undefined,
    error: undefined,
    loading: true,
    refreshing: false,
  });

  // Guards against a slow earlier request resolving after a newer one and
  // overwriting fresher data.
  const requestId = useRef(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const run = useCallback(() => {
    const id = ++requestId.current;
    setState((s) => ({ ...s, loading: s.data === undefined, refreshing: s.data !== undefined }));

    fetcherRef
      .current()
      .then((data) => {
        if (id !== requestId.current) return;
        setState({ data, error: undefined, loading: false, refreshing: false });
      })
      .catch((err: unknown) => {
        if (id !== requestId.current) return;
        setState((s) => ({
          ...s,
          error: err instanceof Error ? err.message : "Request failed",
          loading: false,
          refreshing: false,
        }));
      });
  }, []);

  useEffect(run, deps); // eslint-disable-line react-hooks/exhaustive-deps

  return { ...state, reload: run };
}
