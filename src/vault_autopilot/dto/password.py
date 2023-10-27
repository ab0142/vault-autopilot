from typing import Literal

import pydantic
from pydantic.dataclasses import dataclass
from typing_extensions import Annotated, TypedDict

from . import base

StringEncodingType = Literal["base64", "utf8"]


class PasswordSecretKeys(TypedDict):
    secret_key: str


class PasswordSpec(base.SecretEngineMixin, base.PathMixin):
    secret_keys: PasswordSecretKeys
    policy_path: str
    cas: Annotated[int, pydantic.Field(ge=0)]
    encoding: Annotated[StringEncodingType, pydantic.Field(default="utf8")]


@dataclass(slots=True)
class PasswordCreateDTO(base.BaseDTO):
    spec: PasswordSpec

    def full_path(self) -> str:
        return "{0[secret_engine]}/{0[secret_keys][secret_key]}".format(self.spec)
