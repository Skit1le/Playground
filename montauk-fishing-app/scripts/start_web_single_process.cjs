const { startServer } = require("../node_modules/next/dist/server/lib/start-server");
const path = require("path");

const port = Number(process.env.PORT || 3001);

startServer({
  dir: path.join(__dirname, "..", "apps", "web"),
  port,
  allowRetry: true,
  isDev: true,
  hostname: "127.0.0.1",
}).catch((error) => {
  console.error(error);
  process.exit(1);
});
