// ponytail: post-build snapshot step for public marketing routes only.
// Runs after `vite build`. Uses vite's own SSR module loader (no extra
// TS/JSX transform tool) to render each route via src/entry-server.tsx,
// then splices the result into the already-built dist/index.html template.
import { createServer } from 'vite'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(__dirname, '..')
const distDir = path.join(root, 'dist')

const STATIC_ROUTES = ['/', '/privacy', '/cookies', '/data-disclosure', '/for-investors', '/for-engineers']

function outputPathFor(route) {
  return route === '/' ? path.join(distDir, 'index.html') : path.join(distDir, route.slice(1), 'index.html')
}

// medicoord.nknext.dev is the real production domain (verified against the
// live Vercel project) — medicoordai.com is not registered on the account.
const PRODUCTION_DOMAIN = 'https://medicoord.nknext.dev'

function injectTemplate(template, { route, title, description, rootHtml }) {
  const canonical = `${PRODUCTION_DOMAIN}${route === '/' ? '' : route}`
  return template
    .replace(/<title>[^<]*<\/title>/, `<title>${title}</title>`)
    .replace(/(<meta name="description" content=")[^"]*(")/, `$1${description}$2`)
    .replace(/(<meta property="og:title" content=")[^"]*(")/, `$1${title}$2`)
    .replace(/(<meta property="og:description" content=")[^"]*(")/, `$1${description}$2`)
    .replace(/(<meta property="og:url" content=")[^"]*(")/, `$1${canonical}$2`)
    .replace(/(<link rel="canonical" href=")[^"]*(")/, `$1${canonical}$2`)
    .replace(/(<meta name="twitter:title" content=")[^"]*(")/, `$1${title}$2`)
    .replace(/(<meta name="twitter:description" content=")[^"]*(")/, `$1${description}$2`)
    .replace('<div id="root"></div>', `<div id="root">${rootHtml}</div>`)
}

function assertBuildTimeCheck(route, { title, description, rootHtml }) {
  const failures = []
  if (!title || !title.trim()) failures.push('empty <title>')
  if (!description || !description.trim()) failures.push('empty meta description')
  if (!rootHtml || rootHtml.length < 200) failures.push(`rootHtml too short (${rootHtml?.length ?? 0} chars)`)
  if (!/<h1[\s>]/i.test(rootHtml ?? '')) failures.push('no <h1> content anchor found')
  if (failures.length > 0) {
    throw new Error(`Prerender check failed for ${route}: ${failures.join(', ')}`)
  }
}

// Guards the output HTML itself (post-injectTemplate), catching regressions
// like a missing og:image or a stale/wrong hardcoded domain slipping back in.
function assertOutputHtml(route, html) {
  const failures = []
  if (!new RegExp(`<meta property="og:image" content="${PRODUCTION_DOMAIN}/[^"]+"`).test(html)) {
    failures.push('missing or non-absolute og:image')
  }
  if (!html.includes('<meta name="twitter:card" content="summary_large_image">') &&
      !html.includes('<meta name="twitter:card" content="summary_large_image" />')) {
    failures.push('missing twitter:card')
  }
  if (!html.includes(`content="${PRODUCTION_DOMAIN}`)) {
    failures.push(`canonical/og:url does not use ${PRODUCTION_DOMAIN}`)
  }
  if (html.includes('medicoordai.com')) {
    failures.push('stale medicoordai.com domain found in output')
  }
  if (failures.length > 0) {
    throw new Error(`Prerender output check failed for ${route}: ${failures.join(', ')}`)
  }
}

async function main() {
  const template = await readFile(path.join(distDir, 'index.html'), 'utf-8')

  // dist/index.html is about to be overwritten with the prerendered landing page. Client-only
  // routes (/app, /setup, ...) need the empty shell instead, so keep a copy for the Vercel
  // catch-all rewrite (vercel.json -> /spa; cleanUrls serves spa.html there).
  await writeFile(path.join(distDir, 'spa.html'), template, 'utf-8')

  const vite = await createServer({
    root,
    server: { middlewareMode: true },
    appType: 'custom',
  })

  try {
    const { CASE_STUDIES } = await vite.ssrLoadModule('/src/data/caseStudies.ts')
    const caseStudyRoutes = CASE_STUDIES.map((cs) => `/for-engineers/${cs.slug}`)
    const routes = [...STATIC_ROUTES, ...caseStudyRoutes]

    const { render } = await vite.ssrLoadModule('/src/entry-server.tsx')

    for (const route of routes) {
      const result = await render(route)
      assertBuildTimeCheck(route, result)

      const html = injectTemplate(template, { route, ...result })
      assertOutputHtml(route, html)
      const outPath = outputPathFor(route)
      await mkdir(path.dirname(outPath), { recursive: true })
      await writeFile(outPath, html, 'utf-8')
      console.log(`prerendered ${route} -> ${path.relative(root, outPath)} (title: "${result.title}")`)
    }

    console.log(`\nPrerendered ${routes.length} routes successfully.`)
  } finally {
    await vite.close()
  }
}

main()
  .then(() => process.exit(0)) // ponytail: some dep (motion/jsdom) leaves a handle open; short-lived build script, safe to force-exit once files are written
  .catch((err) => {
    console.error(err)
    process.exit(1)
  })
