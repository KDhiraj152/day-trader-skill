#!/usr/bin/env node
"use strict";

// trader-skill: installs the Trader skill pack for your agent.
// `npx trader-skill` copies the 12 bundled skill folders into the current
// directory (or --dir). Plain Node, no dependencies, works on Node 14 up.

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");

function version() {
  return JSON.parse(fs.readFileSync(path.join(ROOT, "plugin.json"), "utf8")).version;
}

function skills() {
  return fs.readdirSync(ROOT)
    .filter((d) => d.startsWith("trader-") && fs.statSync(path.join(ROOT, d)).isDirectory())
    .sort();
}

function describe(name) {
  const skill = path.join(ROOT, name, "SKILL.md");
  let text;
  try {
    text = fs.readFileSync(skill, "utf8").slice(0, 4000);
  } catch (err) {
    return "";
  }
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.startsWith("description:")) continue;
    const value = line.slice("description:".length).trim();
    if (![">-", ">", "|-", "|"].includes(value)) return value;
    // a folded block: the description is the indented lines below
    const words = [];
    for (let j = i + 1; j < lines.length; j++) {
      const follow = lines[j];
      if (!/^\s/.test(follow)) break;
      words.push(follow.trim());
    }
    return words.join(" ");
  }
  return "";
}

function copyTree(from, to) {
  fs.mkdirSync(to, { recursive: true });
  for (const entry of fs.readdirSync(from, { withFileTypes: true })) {
    const src = path.join(from, entry.name);
    const dst = path.join(to, entry.name);
    if (entry.isDirectory()) copyTree(src, dst);
    else fs.copyFileSync(src, dst);
  }
}

function usage() {
  console.log("trader-skill " + version() + ": installs the Trader skill pack for your agent\n");
  console.log("  npx trader-skill              copy the 12 skill folders into this directory");
  console.log("  npx trader-skill --dir DIR    copy into DIR instead");
  console.log("  npx trader-skill --skills trader-scanner,trader-news");
  console.log("  npx trader-skill --list       what is in the pack");
  console.log("\nThen point your agent's skill loader at the folder and load every SKILL.md.");
}

function main() {
  const args = process.argv.slice(2);
  if (args.includes("--version") || args.includes("-v")) {
    console.log("trader-skill " + version());
    return 0;
  }
  if (args.includes("--help") || args.includes("-h") || args.includes("help")) {
    usage();
    return 0;
  }
  if (args.includes("--list") || args.includes("list")) {
    for (const s of skills()) console.log(s.padEnd(20) + describe(s).slice(0, 90));
    return 0;
  }
  const dirArg = args.indexOf("--dir");
  const dest = path.resolve(dirArg >= 0 ? (args[dirArg + 1] || ".") : ".");
  fs.mkdirSync(dest, { recursive: true });
  let wanted = skills();
  const skillsArg = args.indexOf("--skills");
  if (skillsArg >= 0) {
    const asked = (args[skillsArg + 1] || "").split(",").map((s) => s.trim()).filter(Boolean);
    const unknown = asked.filter((s) => !wanted.includes(s));
    if (unknown.length) {
      console.error("No such skill: " + unknown.join(", "));
      console.error("The pack ships: " + wanted.join(", "));
      return 2;
    }
    wanted = asked;
  }
  const force = args.includes("--force");
  for (const name of wanted) {
    const target = path.join(dest, name);
    if (fs.existsSync(target) && !force) {
      console.error(target + " is already there; pass --force to overwrite");
      return 2;
    }
    copyTree(path.join(ROOT, name), target);
  }
  console.log("Installed " + wanted.length + " skill folders into " + dest + ":");
  for (const name of wanted) console.log("  " + name);
  console.log("");
  console.log("Next: point your agent's skill loader at " + dest + " and load every SKILL.md.");
  console.log("No loader? Paste any single SKILL.md at the top of a chat and it works as a mode.");
  console.log("The research desk optionally reads a local OpenBB server; see its SKILL.md.");
  return 0;
}

process.exit(main());
