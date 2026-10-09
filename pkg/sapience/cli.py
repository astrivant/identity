"""
Route lightweight lesson lookup independently of optional analytics dependencies.
"""

from __future__ import annotations

import sys

__all__ = ["main"]


def main() -> int:
    """
    Dispatch lesson operations or the existing hierarchy commands.

    Returns:
        int: Selected command status; database failures remain credential-safe.
    """
    if len(sys.argv) > 1 and sys.argv[1] == "repertoire":
        from sapience.repertoire.cli import main as repertoire_main

        return repertoire_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "privacy":
        from sapience.privacy.cli import main as privacy_main

        return privacy_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "registry":
        from sapience.registry.names import main as registry_main

        return registry_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "init":
        from sapience.project import main as init_main

        return init_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "lessons":
        from sapience.storage.cli import main as lessons_main

        return lessons_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "life":
        from sapience.life.cli import main as life_main

        return life_main(sys.argv[2:])

    from sapience.knowledge.cli import main as knowledge_main

    return knowledge_main()
