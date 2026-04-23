import { createClient } from '@supabase/supabase-js';
// 대시보드는 **읽기 전용**. anon key 사용.
const url = import.meta.env.VITE_SUPABASE_URL;
const anon = import.meta.env.VITE_SUPABASE_ANON_KEY;
if (!url || !anon) {
    // 개발 편의를 위해 경고만. 실제 배포 시 빌드 단계에서 필수.
    console.warn('[dashboard] VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY 미설정. ' +
        '.env 를 채우세요.');
}
export const supabase = createClient(url ?? '', anon ?? '');
export const TRADE_SYMBOL = import.meta.env.VITE_TRADE_SYMBOL ?? 'KRW-BTC';
