/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ARES_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
