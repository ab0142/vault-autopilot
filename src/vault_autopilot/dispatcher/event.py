import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Generic, Sequence, Type, TypeVar, Union

from .. import dto, util

T = TypeVar("T")

FilterType = Sequence[Type[T]]
CallbackType = Callable[[Any], Coroutine[Any, Any, Any]]


@dataclass(slots=True)
class HandlerObject(Generic[T]):
    filter: FilterType[T]
    callback: CallbackType


@dataclass(slots=True)
class EventObserver(Generic[T]):
    _handlers: list[HandlerObject[T]] = field(init=False, default_factory=list)

    def register(self, filter_: FilterType[T], callback: CallbackType) -> None:
        self._handlers.append(HandlerObject(filter_, callback))

    async def trigger(self, event: T) -> None:
        async with asyncio.TaskGroup() as tg:
            for handler in filter(lambda h: type(event) in h.filter, self._handlers):
                await util.coro.create_task_limited(
                    tg, util.coro.BoundlessSemaphore(), handler.callback(event)
                )


@dataclass(slots=True)
class PasswordDiscovered:
    payload: dto.PasswordCreateDTO


@dataclass(slots=True)
class PasswordCreated:
    payload: dto.PasswordCreateDTO


@dataclass(slots=True)
class PasswordUpdated:
    payload: dto.PasswordCreateDTO


@dataclass(slots=True)
class PasswordUnchanged:
    payload: dto.PasswordCreateDTO


@dataclass(slots=True)
class IssuerDiscovered:
    payload: dto.IssuerCreateDTO


@dataclass(slots=True)
class IssuerCreated:
    payload: dto.IssuerCreateDTO


@dataclass(slots=True)
class IssuerUpdated:
    payload: dto.IssuerCreateDTO


@dataclass(slots=True)
class IssuerUnchanged:
    payload: dto.IssuerCreateDTO


@dataclass(slots=True)
class PasswordPolicyDiscovered:
    payload: dto.PasswordPolicyCreateDTO


@dataclass(slots=True)
class PasswordPolicyCreated:
    payload: dto.PasswordPolicyCreateDTO


@dataclass(slots=True)
class PasswordPolicyUpdated:
    payload: dto.PasswordPolicyCreateDTO


@dataclass(slots=True)
class PasswordPolicyUnchanged:
    payload: dto.PasswordPolicyCreateDTO


@dataclass(slots=True)
class PostProcessRequested:
    """
    After all manifests have been processed, this event is triggered by the dispatcher,
    providing an opportunity to examine resources with unsatisfied dependencies. This
    can include situations such as passwords awaiting configuration of password policies
    or intermediate issuers waiting for configuration of root issuers.

    See also:
        * :class:`PasswordConfigured`
        * :class:`IssuerConfigured`
        * :class:`PasswordPolicyConfigured`
    """


ResourceDiscovered = Union[
    PasswordDiscovered, IssuerDiscovered, PasswordPolicyDiscovered
]
PasswordConfigured = Union[PasswordCreated, PasswordUpdated, PasswordUnchanged]
IssuerConfigured = Union[IssuerCreated, IssuerUpdated, IssuerUnchanged]
PasswordPolicyConfigured = Union[
    PasswordPolicyCreated, PasswordPolicyUpdated, PasswordPolicyUnchanged
]


EventType = Union[
    PasswordDiscovered,
    PasswordCreated,
    PasswordUpdated,
    PasswordUnchanged,
    IssuerDiscovered,
    IssuerCreated,
    IssuerUpdated,
    IssuerUnchanged,
    PasswordPolicyDiscovered,
    PasswordPolicyCreated,
    PasswordPolicyUpdated,
    PasswordPolicyUnchanged,
    PostProcessRequested,
]
