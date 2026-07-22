/**
 * Build Tailwind CSS via standalone CLI (tools/tailwindcss.exe).
 * Uso: node tools/build-css.js [--watch]
 */
const { spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");

const root = path.resolve(__dirname, "..");
const bin = path.join(root, "tools", process.platform === "win32" ? "tailwindcss.exe" : "tailwindcss");
const input = path.join(root, "src", "styles.css");
const output = path.join(root, "static", "css", "app.css");
const config = path.join(root, "tailwind.config.js");

if (!fs.existsSync(bin)) {
  console.error("CLI não encontrado em tools/. Baixe o standalone Tailwind CSS.");
  process.exit(1);
}

fs.mkdirSync(path.dirname(output), { recursive: true });

const args = ["-i", input, "-o", output, "-c", config, "--minify"];
if (process.argv.includes("--watch")) args.push("--watch");

const result = spawnSync(bin, args, { cwd: root, stdio: "inherit" });
process.exit(result.status ?? 1);
