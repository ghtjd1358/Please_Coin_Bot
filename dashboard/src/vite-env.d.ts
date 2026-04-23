/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL: string;
  readonly VITE_SUPABASE_ANON_KEY: string;
  readonly VITE_TRADE_SYMBOL?: string;
  readonly VITE_BASE_INTERVAL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
