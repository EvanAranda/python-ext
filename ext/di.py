import functools as ft
from types import TracebackType
from typing import (
    Any,
    Callable,
    ContextManager,
    Generator,
    Generic,
    Mapping,
    TypeVar,
    Union,
)

from pydantic_settings import BaseSettings

T = TypeVar("T")

Factory = Callable[..., T]
Dependency = Factory[T]


class Service(Generic[T]):
    _factory: Factory[T]
    _deps: Mapping[str, Dependency[Any]]

    def __init__(self) -> None:
        self._name: str | None = None

    def factory(self, **deps: Dependency[Any]) -> T:
        raise NotImplementedError()

    @property
    def name(self) -> str:
        return self._name or self._factory.__name__

    @name.setter
    def name(self, name: str):
        self._name = name

    def _resolve_deps(self, deps: dict) -> dict[str, Any]:
        deps = {**deps, **self._deps}
        for k, dep in deps.items():
            if isinstance(dep, Service):
                deps[k] = dep()
        return deps

    def _call_factory(self, **deps: Dependency[Any]) -> T:
        return self._factory(**self._resolve_deps(deps))

    def __call__(self, **deps: Dependency[Any]) -> T:
        return self.factory(**deps)

    def __str__(self) -> str:
        return f"<{self.__class__.__name__} {self.name}>"


class value(Service[T], Generic[T]):
    def __init__(self, value: T) -> None:
        super().__init__()
        self._value = value
        self._name = repr(value)

    def factory(self, **deps: Dependency[Any]) -> T:
        return self._value


class transient(Service[T], Generic[T]):
    def __init__(
        self,
        factory: Factory[T],
        **deps: Dependency[Any],
    ) -> None:
        super().__init__()
        self._factory = factory
        self._deps = deps

    def factory(self, **deps: Dependency[Any]) -> T:
        return self._call_factory(**deps)


class singleton(Service[T], Generic[T]):
    def __init__(self, factory: Factory[T], **deps: Dependency[Any]) -> None:
        super().__init__()
        self._factory = factory
        self._deps = deps
        self._instance: T | None = None

    def factory(self, **deps: Dependency[Any]) -> T:
        if self._instance is None:
            self._instance = self._call_factory(**deps)
        return self._instance


class config(Service[T], Generic[T]):
    def __init__(self, conf: Dependency[T]):
        super().__init__()

        if isinstance(conf, type) and issubclass(conf, BaseSettings):
            conf = singleton(conf)  # type: ignore

        self._factory = conf

    def factory(self, **deps: Dependency[Any]) -> T:
        return self._factory()

    def __getattr__(self, __name: str):
        return _subconfig(self, __name)


class _subconfig(Service):
    def __init__(self, parent, attr: str):
        super().__init__()
        self._parent = parent
        self._attr = attr

    def factory(self, **deps: Dependency[Any]) -> Any:
        return getattr(self._parent(), self._attr)

    def __getattr__(self, __name: str):
        return _subconfig(self, __name)


class partial(Service[T], Generic[T]):
    def __init__(self, func: T, **deps: Dependency[Any]):
        super().__init__()
        self._func = func
        self._deps = deps

    def factory(self, **deps: Dependency[Any]) -> T:
        return ft.partial(self._func, **self._resolve_deps(deps))  # type: ignore


Initializer = Union[Generator[None, None, T], ContextManager[T]]
Disposer = Callable


class resource(Service[T]):
    def __init__(
        self,
        initializer: Factory[Initializer[T]],
        **deps: Dependency[Any],
    ):
        super().__init__()
        self._initializer = initializer
        self._deps = deps
        self._factory = None  # type: Factory[T] | None

    def factory(self, **_: Dependency[Any]) -> T:
        if self._factory is None:
            raise RuntimeError("resource not initialized")
        return self._call_factory()

    def setup(self) -> Disposer:
        initializer = self._initializer(**self._resolve_deps({}))

        if isinstance(initializer, Generator):
            instance = initializer.__next__()
            self._factory = value(instance)  # type: ignore

            def dispose(*args, **kwargs):
                self._factory = None
                try:
                    initializer.__next__()
                except StopIteration:
                    pass

            return dispose

        if isinstance(initializer, ContextManager):
            instance = initializer.__enter__()
            self._factory = value(instance)

            def dispose(*args, **kwargs):
                self._factory = None
                initializer.__exit__(*args, **kwargs)

            return dispose

        raise RuntimeError("invalid initializer")


class setup_resources(ContextManager[None]):
    def __init__(self, *resources: resource[Any]):
        self._resources = resources
        self._disposers = []

    def __enter__(self) -> None:
        for resource in self._resources:
            self._disposers.append(resource.setup())

    def __exit__(
        self,
        __exc_type: type[BaseException] | None,
        __exc_value: BaseException | None,
        __traceback: TracebackType | None,
    ) -> bool | None:
        for disposer in reversed(self._disposers):
            disposer(__exc_type, __exc_value, __traceback)
