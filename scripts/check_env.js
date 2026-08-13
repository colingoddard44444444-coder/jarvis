// Quick environment sanity check for the Electron side.
const { execSync } = require("child_process");

function has(cmd) {
  try {
    execSync(`${cmd} -version`, { stdio: "ignore", timeout: 5000 });
    return true;
  } catch {
    return false;
  }
}

console.log("Node", process.version);
const checks = ["ffmpeg", "ffprobe", "yt-dlp", "python3"];
let ok = true;
for (const c of checks) {
  const present = has(c);
  console.log(`  [${present ? "OK " : "MISS"}] ${c}`);
  if (!present) ok = false;
}
if (!ok) {
  console.log("\nRun scripts/setup_popos.sh to install missing tools.");
  process.exit(1);
}
console.log("\nEnvironment looks good.");
