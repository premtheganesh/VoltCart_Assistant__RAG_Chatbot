import type { NextConfig } from "next";

// Sites allowed to show the chat widget in an iframe (space-separated origins, e.g.
// "https://voltcart.example https://shop.voltcart.example"). "*" allows any site: fine for local
// development, but set the real store's origin in production.
const widgetParents = process.env.WIDGET_ALLOWED_PARENTS ?? "*";

const config: NextConfig = {
  reactStrictMode: true,
  output: "standalone", // a self-contained server for the Docker image
  poweredByHeader: false, // don't advertise the framework in every response
  // The dev server only serves its scripts to the hosts it expects. localhost and 127.0.0.1 are
  // the same machine but different "origins" to a browser, so allow both
  allowedDevOrigins: ["localhost", "127.0.0.1"],

  async headers() {
    return [
      {
        // Clickjacking protection: no other site may show these pages in a frame (an attacker
        // could overlay the admin panel and trick a click). Only /widget is meant to be framed.
        source: "/((?!widget$).*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
        ],
      },
      {
        source: "/widget",
        headers: [{ key: "Content-Security-Policy", value: `frame-ancestors ${widgetParents}` }],
      },
      { source: "/:path*", headers: [{ key: "Referrer-Policy", value: "strict-origin-when-cross-origin" }] },
    ];
  },
};

export default config;
