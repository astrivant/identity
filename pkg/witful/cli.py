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
    if len(sys.argv) > 1 and sys.argv[1] == "delivery":
        from witful.delivery.cli import main as delivery_main

        return delivery_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "completion":
        from witful.completion.cli import main as completion_main

        return completion_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "instances":
        from witful.instances.cli import main as instances_main

        return instances_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "sapience":
        from witful.sapience.cli import main as sapience_main

        return sapience_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "sleeve":
        from witful.sleeves.cli import main as sleeve_main

        return sleeve_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "collection":
        from witful.collection.cli import main as collection_main

        return collection_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "awareness":
        from witful.awareness.cli import main as awareness_main

        return awareness_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "checkpoints":
        from witful.checkpoints.cli import main as checkpoints_main

        return checkpoints_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "repertoire":
        from witful.repertoire.cli import main as repertoire_main

        return repertoire_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "privacy":
        from witful.privacy.cli import main as privacy_main

        return privacy_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "registry":
        from witful.registry.names import main as registry_main

        return registry_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "init":
        from witful.project import main as init_main

        return init_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "lessons":
        from witful.storage.cli import main as lessons_main

        return lessons_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "reflection":
        from witful.reflection.cli import main as reflection_main

        return reflection_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "life":
        from witful.life.cli import main as life_main

        return life_main(sys.argv[2:])

    from witful.knowledge.cli import main as knowledge_main

    return knowledge_main()
