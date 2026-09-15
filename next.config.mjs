/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  // Dynamic app routes (e.g. /en) export as a same-named "route.html" file
  // *and* a "route/" directory holding RSC prefetch payloads, with no
  // index.html inside. GitHub Pages resolves a directory before its sibling
  // .html file, so the bare page (e.g. /en) 404s. Trailing slashes make Next
  // place index.html inside that directory instead, removing the clash.
  trailingSlash: true,
  // Served at igormcsouza.github.io/resume, a project subpath rather than
  // the domain root.
  basePath: "/resume",
  assetPrefix: "/resume",
  turbopack: {
    rules: {
      "*.svg": {
        loaders: [{ loader: "@svgr/webpack", options: { icon: true } }],
        as: "*.js",
      },
    },
  },
};

export default nextConfig;
