## Notice

This is a thrid party thing, not supported or endorsed by the [Haiku® Project](http://www.haiku-os.org). It's also not supposed to live long.

It is a by-product of something else already not serious itself, and it has been accumulating stuff since it was born. Don't expect even correctness. If you want to help, do it at the project trying to [do the right thing within concourse](https://www.haiku-os.org/blog/ritz/2021-05-22_gsoc_2021_coding_style_checker_bot_for_gerrit/).

## Installation

Why would you want that?

You'll need python 3, and will probably want to run it in a virtual environment. The extra modules are listed in the requirements file.

Copy `config.dist` to `config.ini` and edit it to your liking. Only fill in the credentials if you want to report back to gerrit, which you shouldn't do if there's already an instance doing it.

Build the buildtools for your arches. Clone the haiku repo, make a branch tracking the remote master (name branch_base in the config file) and yet another branch based off that (name branch_rolling in the config file). You'll very probably want a worktree just for the scripts, as they'll be checking out and resetting stuff while running.

The entry point is `testbuilds.py`. You'll probably want to run it on a timer. You will want to run it in a container, VM or some other sandboxed environment: it is retrieving unknown changes, and that includes scripts that are run during the build.

There's no web app. If you want to make files and build logs available, you just need something to serve files. With that set up, copy the files in the web directory to your www root and you are ready to go.

## FAQ

### Why do you...?

A mix of "history" and "I'm not a real programmer" answers most of those.

### Will you integrate this in concourse?

No. Smarter people are working on doing that the right way. I don't even think there would be anything of use here.

### Will you also follow the betas?

Highly unlikely. And it's probably easier to start another instance pointing to that branch than to make this follow several branches.

### What are all those branches?

For each active change, there's a `changeset-${Change-Id}-${version}` branch. They are removed once the change is not active.

## Legal

Haiku® and the HAIKU logo® are registered trademarks of [Haiku, Inc](http://www.haiku-inc.org). and are developed by the [Haiku Project](http://www.haiku-os.org).
