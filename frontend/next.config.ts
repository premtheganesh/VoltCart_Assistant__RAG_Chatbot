import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false, // don't advertise the framework in every response
  // The dev server only serves its scripts to the hosts it expects. localhost and 127.0.0.1 are
  // the same machine but different "origins" to a browser, so allow both
  allowedDevOrigins: ["localhost", "127.0.0.1"],
};

export default config;
