// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://docs.speechrouter.ai',
  integrations: [
    starlight({
      title: 'SpeechRouter',
      favicon: '/favicon.svg',
      logo: { src: './src/assets/logo.svg', alt: '' },
      description:
        'One API for every speech model — 12 providers, mid-stream failover, vendor list prices at 0% markup.',
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/speech-router/speechrouter' },
      ],
      customCss: [
        '@fontsource/ibm-plex-mono/400.css',
        '@fontsource/ibm-plex-mono/500.css',
        '@fontsource/ibm-plex-mono/600.css',
        '@fontsource/ibm-plex-sans/400.css',
        '@fontsource/ibm-plex-sans/500.css',
        '@fontsource/ibm-plex-sans/600.css',
        './src/styles/brand.css',
      ],
      components: {
        ThemeProvider: './src/components/ForceDark.astro',
        ThemeSelect: './src/components/Empty.astro',
      },
      expressiveCode: {
        themes: ['github-dark'],
        styleOverrides: {
          borderColor: '#3a332a',
          borderRadius: '0.5rem',
          codeBackground: '#171310',
          frames: {
            shadowColor: 'rgba(0,0,0,0.45)',
            editorTabBarBackground: '#1b1712',
            editorActiveTabBackground: '#241e16',
            editorActiveTabIndicatorTopColor: '#e8a33d',
            editorBackground: '#171310',
            terminalBackground: '#171310',
            terminalTitlebarBackground: '#1b1712',
          },
        },
      },
      sidebar: [
        {
          label: 'Start here',
          items: [
            { label: 'Introduction', slug: 'intro' },
            { label: 'Quickstart', slug: 'quickstart' },
            { label: 'Authentication', slug: 'authentication' },
          ],
        },
        {
          label: 'Guides',
          items: [
            { label: 'Streaming transcription', slug: 'guides/streaming' },
            { label: 'Batch transcription', slug: 'guides/batch' },
            { label: 'Failover', slug: 'guides/failover' },
            { label: 'Deepgram compatibility', slug: 'guides/deepgram-compat' },
            { label: 'Bring your own keys', slug: 'guides/byok' },
            { label: 'Pricing & billing', slug: 'guides/pricing' },
          ],
        },
        {
          label: 'Providers',
          items: [{ autogenerate: { directory: 'providers' } }],
        },
        {
          label: 'Reference',
          items: [
            { label: 'REST API', slug: 'reference/rest' },
            { label: 'WebSocket events', slug: 'reference/events' },
            { label: 'Errors & close codes', slug: 'reference/errors' },
          ],
        },
        {
          label: 'SDKs',
          items: [
            { label: 'JavaScript / TypeScript', slug: 'sdks/javascript' },
            { label: 'Python', slug: 'sdks/python' },
          ],
        },
      ],
    }),
  ],
});
