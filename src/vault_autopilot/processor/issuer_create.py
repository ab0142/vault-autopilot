import asyncio
import logging
from dataclasses import dataclass
from itertools import chain
from typing import Union

from .. import dto, state, util
from ..dispatcher import event
from . import abstract

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Node(util.dep_manager.AbstractNode):
    payload: dto.IssuerCreateDTO

    def __hash__(self) -> int:
        return hash(self.payload.absolute_path())

    def __repr__(self) -> str:
        return f"Node({self.payload.absolute_path()})"

    @classmethod
    def from_payload(cls, payload: dto.IssuerCreateDTO) -> "Node":
        """
        Creates a node from given payload.

        Args:
            payload: The payload containing the information to create the node.
            status: The initial status of the node.
        """
        return cls(payload)


@dataclass(slots=True)
class PlaceholderNode:
    """Efficiently represents a :class:Node object before its details are available.

    This class enables ordering dependencies without waiting for the full node
    information.

    Args:
        node_hash: The hash of the placeholder node.
    """

    node_hash: int

    def __hash__(self) -> int:
        return self.node_hash

    @classmethod
    def from_issuer_absolute_path(cls, path: str) -> "PlaceholderNode":
        """Create a new :class:`PlaceholderNode` instance from an issuer absolute path.

        Args:
            path: The PKI engine mount path followed by the issuer name, separated
                by a forward slash. For example: ``pki/my-issuer``.
        """
        return cls(hash(path))


NodeType = Union[Node, PlaceholderNode]


@dataclass(slots=True)
class IssuerCreateProcessor(abstract.AbstractProcessor):
    state: state.IssuerState

    def register_handlers(self) -> None:
        async def _on_issuer_discovered(ev: event.IssuerDiscovered) -> None:
            """
            Responds to the :class:`event.IssuerDiscovered` event by performing the
            following tasks:

            #. If the payload includes issuance parameters, it checks whether the root
               issuer already exists on the Vault server. If it does, it schedules all
               known intermediates, including the current one, to be created on the
               Vault server, setting up a proper dependency chain. If the root issuer
               does not exist, it creates the given intermediate issuer later when the
               root CA is set up (the processor memorizes the payload).
            #. If the payload does not include issuance parameters, the function creates
               the issuer immediately without establishing dependencies.
            """
            if ev.payload.spec.get("issuance_params"):
                async with self.state.dep_mgr.lock() as mgr:
                    if (
                        root := mgr.get_node_by_hash(
                            (root_hash := hash(ev.payload.isser_ref_absolute_path())),
                            None,
                        )
                    ) is None:
                        root = PlaceholderNode(node_hash=root_hash)
                        mgr.add_node(root)

                    intermediate = Node.from_payload(ev.payload)
                    if (
                        existing_intermediate := mgr.get_node_by_hash(
                            hash(ev.payload.absolute_path()),
                            None,
                        )
                    ) is None:
                        mgr.add_node(intermediate)
                    elif isinstance(existing_intermediate, PlaceholderNode):
                        mgr.relabel_nodes(((existing_intermediate, intermediate),))
                        del existing_intermediate
                    else:
                        raise RuntimeError("Duplicates aren't allowed: %r" % ev.payload)

                    mgr.add_edge(root, intermediate, "unsatisfied")

                    if not mgr.are_edges_satisfied(root):
                        # skip creating intermediates as the root is not yet
                        # available
                        return
            else:
                async with self.state.dep_mgr.lock() as mgr:
                    if (
                        root := mgr.get_node_by_hash(
                            (root_hash := hash(ev.payload.absolute_path())),
                            None,
                        )
                    ) is None:
                        root = PlaceholderNode(node_hash=root_hash)
                        mgr.add_node(root)

                await self._process(ev.payload)

            await self._fulfill_unsatisfied_intermediates(root)

        async def _on_postprocess_requested(_: event.PostProcessRequested) -> None:
            """
            Responds to the :class:`event.PostProcessRequested` event by processing any
            unsatisfied issuer nodes.

            Args:
                _: The event triggered by the dispatcher when post-processing is
                    requested.
            """
            await self._force_issuer_creation_despite_root_absence()

        self.state.observer.register((event.IssuerDiscovered,), _on_issuer_discovered)
        self.state.observer.register(
            (event.PostProcessRequested,), _on_postprocess_requested
        )

    async def _process(self, payload: dto.IssuerCreateDTO) -> None:
        """Processes the given payload."""
        await self.state.iss_svc.create(payload)
        # TODO: Unchanged/Updated events
        await self.state.observer.trigger(event.IssuerCreated(payload))

    async def _fulfill_unsatisfied_intermediates(self, root: NodeType) -> None:
        logger.debug("fulfilling intermediates for root: %r", hash(root))
        async with self.state.dep_mgr.lock() as mgr:
            for intermediate in (
                unsatisfied_intermediates := tuple(mgr.find_unsatisfied_nodes(root))
            ):
                mgr.update_edge_status(root, intermediate, status="in_process")

        async with asyncio.TaskGroup() as tg:
            for intermediate in unsatisfied_intermediates:
                assert isinstance(intermediate, Node)
                logger.debug("creating task for intermediate %r", hash(intermediate))
                await util.coro.create_task_limited(
                    tg, self.state.sem, self._process(intermediate.payload)
                )

        if not unsatisfied_intermediates:
            logger.debug("no outbound edges were found for node %r", hash(root))
            return

        async with self.state.dep_mgr.lock() as mgr:
            for intermediate in unsatisfied_intermediates:
                mgr.update_edge_status(root, intermediate, status="satisfied")

            # Optimize memory usage by replacing nodes with payloads with placeholder
            # nodes. Since the issuer has been created, we no longer need to store the
            # payload data in the node.
            mgr.relabel_nodes(
                chain(
                    (
                        (
                            root,
                            PlaceholderNode.from_issuer_absolute_path(
                                root.payload.absolute_path()
                            ),
                        ),
                    )
                    if isinstance(root, Node)
                    else (),
                    (
                        (
                            intermediate,
                            PlaceholderNode.from_issuer_absolute_path(
                                intermediate.payload.absolute_path()
                            ),
                        )
                        for intermediate in unsatisfied_intermediates
                        if isinstance(intermediate, Node)
                    ),
                )
            )

        for intermediate in unsatisfied_intermediates:
            await self._fulfill_unsatisfied_intermediates(intermediate)

    async def _force_issuer_creation_despite_root_absence(self) -> None:
        """
        Forces the creation of intermediates for which the root has not yet been
        configured, which may cause errors and require careful analysis to resolve.
        """
        async with self.state.dep_mgr.lock() as mgr:
            for root, intmd in (edges := tuple(mgr.find_all_unsatisfied_edges())):
                mgr.update_edge_status(root, intmd, status="in_process")

        async with asyncio.TaskGroup() as tg:
            for root, intmd in edges:
                if not isinstance(intmd, Node):
                    logger.debug(
                        "Unable to force the node to be processed as it has "
                        "no payload."
                    )
                    continue

                logger.debug("forcing processing of node: %r", hash(intmd))
                await util.coro.create_task_limited(
                    tg, util.coro.BoundlessSemaphore(), self._process(intmd.payload)
                )
