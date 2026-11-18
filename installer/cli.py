"""trader-skill: the installer for the Trader skill pack.

The wheel ships every skill folder. `trader-skill install` copies them out
of the installed package and into a folder your agent reads skills from.
Standard library only; works wherever the pack itself works.
"""

import argparse
import json
import os
import shutil
import sys

_PACK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_pack")
HOME_SKILLS = os.path.join("~", ".agents", "skills")


def pick_destination(explicit=None):
    """Where the skills go: --dir wins, then ./skills if this project has
    one, else the cross-agent skills folder in your home directory
    (~/.agents/skills), which gets created on the spot."""
    if explicit:
        return os.path.abspath(explicit)
    if os.path.isdir("skills"):
        return os.path.abspath("skills")
    return os.path.abspath(os.path.expanduser(HOME_SKILLS))


def _version():
    """The pack version, read from the manifest that ships in the wheel."""
    with open(os.path.join(_PACK, "plugin.json"), encoding="utf-8") as fh:
        return json.load(fh)["version"]


def _skills():
    """The bundled skill folders, sorted."""
    return sorted(d for d in os.listdir(_PACK)
                  if d.startswith("trader-") and os.path.isdir(os.path.join(_PACK, d)))


def _describe(name):
    """The one-line job from the SKILL.md frontmatter, if it parses."""
    path = os.path.join(_PACK, name, "SKILL.md")
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read(4000)
    except OSError:
        return ""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("description:"):
            continue
        value = line.split(":", 1)[1].strip()
        if value not in (">-", ">", "|-", "|"):
            return value
        # a folded block: the description is the indented lines below
        words = []
        for follow in lines[i + 1:]:
            if not follow.startswith((" ", "\t")):
                break
            words.append(follow.strip())
        return " ".join(words)
    return ""


def cmd_install(args):
    skills = _skills()
    wanted = skills
    if args.skills:
        asked = [s.strip() for s in args.skills.split(",") if s.strip()]
        unknown = [s for s in asked if s not in skills]
        if unknown:
            print("No such skill: %s" % ", ".join(unknown), file=sys.stderr)
            print("The pack ships: %s" % ", ".join(skills), file=sys.stderr)
            return 2
        wanted = asked
    dest = pick_destination(args.dir)
    if dest != os.path.dirname(dest):  # not the filesystem root
        os.makedirs(dest, exist_ok=True)
    for name in wanted:
        target = os.path.join(dest, name)
        if os.path.exists(target) and not args.force:
            print("%s is already there; pass --force to overwrite" % target, file=sys.stderr)
            return 2
        shutil.copytree(os.path.join(_PACK, name), target)
    print("Installed %d skill folders into %s:" % (len(wanted), dest))
    for name in wanted:
        print("  %s" % name)
    print()
    print("Next: point your agent's skill loader at %s and load every SKILL.md." % dest)
    if dest.endswith(os.path.join(".agents", "skills")):
        print("Many agents read ~/.agents/skills on their own; no pointer needed.")
    print("No loader? Paste any single SKILL.md at the top of a chat and it works as a mode.")
    print("The research desk optionally reads a local OpenBB server; see its SKILL.md.")
    return 0


def cmd_list(args):
    for name in _skills():
        print("%-20s %s" % (name, _describe(name)[:90]))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="trader-skill",
        description="Install the Trader skill pack: 12 skills for day trading, from pip to your agent's skill folder.")
    ap.add_argument("--version", action="version", version="%(prog)s " + _version())
    sub = ap.add_subparsers(dest="command")
    p_install = sub.add_parser("install", help="copy the skill folders into a directory")
    p_install.add_argument("dir", nargs="?", default=None,
                           help="destination; picked for you when left out "
                                "(./skills if this project has one, else ~/.agents/skills)")
    p_install.add_argument("--skills", default=None, metavar="A,B",
                           help="only these skills, comma separated")
    p_install.add_argument("--force", action="store_true", help="overwrite folders that exist")
    p_install.set_defaults(fn=cmd_install)
    p_list = sub.add_parser("list", help="the skills in this pack")
    p_list.set_defaults(fn=cmd_list)
    args = ap.parse_args(argv)
    if not getattr(args, "command", None):
        ap.print_help()
        return 0
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
