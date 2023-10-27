from dataclasses import dataclass

from .. import dto, util
from .._pkg import asyva
from ..dto.password import StringEncodingType


def encode(value: str, encoding: StringEncodingType) -> str:
    match encoding:
        case "base64":
            return util.encoding.base64_encode(value)
        case "utf8":
            return value
        case _:
            raise NotImplementedError("Unknown string encoding present")


@dataclass(slots=True)
class PasswordService:
    client: asyva.Client

    async def create(self, payload: dto.PasswordCreateDTO) -> None:
        try:
            value = await self.client.generate_password(
                policy_path=payload.spec["policy_path"]
            )
        except asyva.exc.PasswordPolicyNotFoundError as ex:
            # TODO: Instead of just saying "Policy not found", provide the user with a
            #  more informative error message that includes the line number in the
            #  manifest file where the policy path was defined.
            raise ex

        await self.client.create_or_update_secret(
            path=payload.spec["path"],
            data={
                payload.spec["secret_keys"]["secret_key"]: encode(
                    value=value, encoding=payload.spec["encoding"]
                )
            },
            cas=payload.spec["cas"],
            mount_path=payload.spec["secret_engine"],
        )
