import { useMemo } from 'react';
/** history 배열의 tail을 꺼내는 헬퍼. 별도 fetch 없이 파생만. */
export function useLatestSnapshot(history) {
    return useMemo(() => (history.length ? history[history.length - 1] : null), [history]);
}
