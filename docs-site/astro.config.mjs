// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://docs.speechrouter.ai',
  integrations: [
    starlight({
      title: 'SpeechRouter',
      favicon: '/favicon.svg',
      head: [
        // Privacy-friendly analytics by Plausible
        {
          tag: 'script',
          attrs: { async: true, src: 'https://plausible.io/js/pa-pERz3VNfhsS18-GyTgk1n.js' },
        },
        {
          tag: 'script',
          content:
            'window.plausible=window.plausible||function(){(plausible.q=plausible.q||[]).push(arguments)},plausible.init=plausible.init||function(i){plausible.o=i||{}};plausible.init()',
        },
        // Product analytics by PostHog
        {
          tag: 'script',
          content: "!function(t,e){var o,n,p,r;e.__SV||(window.posthog && window.posthog.__loaded)||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(\".\");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement(\"script\")).type=\"text/javascript\",p.crossOrigin=\"anonymous\",p.async=!0,p.src=s.api_host.replace(\".i.posthog.com\",\"-assets.i.posthog.com\")+\"/static/array.js\",(r=t.getElementsByTagName(\"script\")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a=\"posthog\",u.people=u.people||[],u.toString=function(t){var e=\"posthog\";return\"posthog\"!==a&&(e+=\".\"+a),t||(e+=\" (stub)\"),e},u.people.toString=function(){return u.toString(1)+\".people (stub)\"},o=\"an ln init xn Cn Br kn In capture Fn nn calculateEventProperties On register register_once register_for_session unregister unregister_for_session Ln getFeatureFlag getFeatureFlagPayload getFeatureFlagResult getAllFeatureFlags isFeatureEnabled reloadFeatureFlags updateFlags updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures on onFeatureFlags onSurveysLoaded onSessionId getSurveys getActiveMatchingSurveys renderSurvey displaySurvey cancelPendingSurvey canRenderSurvey canRenderSurveyAsync Dn identify setPersonProperties unsetPersonProperties group resetGroups setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags reset shutdown setIdentity clearIdentity get_distinct_id getGroups get_session_id get_session_replay_url alias set_config startSessionRecording stopSessionRecording sessionRecordingStarted captureException addExceptionStep captureLog startExceptionAutocapture stopExceptionAutocapture loadToolbar get_property getSessionProperty An Rn createPersonProfile setInternalOrTestUser $n yn jn opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing get_explicit_consent_status is_capturing clear_opt_in_out_capturing Tn debug Ur Rt getPageViewId captureTraceFeedback captureTraceMetric pn\".split(\" \"),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);\nposthog.init('phc_qBpU7iJEGrNi3hSWbFYbETcBaoe4Vep5fwBKDXe2kVy3', {\n    api_host: 'https://us.i.posthog.com',\n    defaults: '2026-05-30',\n    person_profiles: 'identified_only',\n})",
        },
      ],
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
            { label: 'Which model?', slug: 'choosing-a-model' },
          ],
        },
        {
          label: 'Guides',
          items: [
            { label: 'Streaming transcription', slug: 'guides/streaming' },
            { label: 'Batch transcription', slug: 'guides/batch' },
            { label: 'Failover', slug: 'guides/failover' },
            { label: 'Diarization', slug: 'guides/diarization' },
            { label: 'Keyterm boosting', slug: 'guides/keyterms' },
            { label: 'Audio formats', slug: 'guides/audio' },
            { label: 'Deepgram compatibility', slug: 'guides/deepgram-compat' },
            { label: 'Bring your own keys', slug: 'guides/byok' },
            { label: 'Pricing & billing', slug: 'guides/pricing' },
            { label: 'Self-hosting', slug: 'guides/self-hosting' },
            { label: 'Audio persistence', slug: 'guides/audio-persistence' },
          ],
        },
        {
          label: 'Recipes',
          items: [
            { label: 'Build a voice agent', slug: 'recipes/voice-agent' },
            { label: 'Transcribe phone calls', slug: 'recipes/telephony' },
            { label: 'Generate subtitles', slug: 'recipes/subtitles' },
            { label: 'Live browser captions', slug: 'recipes/browser-captions' },
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
            { label: 'Limits', slug: 'reference/limits' },
          ],
        },
        {
          label: 'Migrate',
          items: [
            { label: 'From Deepgram', slug: 'guides/deepgram-compat' },
            { label: 'From AssemblyAI', slug: 'migrate/from-assemblyai' },
            { label: 'From OpenAI / Whisper', slug: 'migrate/from-openai' },
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
