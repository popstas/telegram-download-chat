import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from telethon.errors import ChatIdInvalidError
from telethon.tl.types import (
    Channel,
    Chat,
    PeerChannel,
    PeerChat,
    PeerUser,
    TypePeer,
    User,
)


class EntitiesMixin:
    async def fetch_user_name(self, user_id: int) -> str:
        try:
            if not self.client:
                await self.connect()
            user = await self.client.get_entity(PeerUser(user_id))
            name = " ".join(
                filter(
                    None,
                    [
                        getattr(user, "first_name", None),
                        getattr(user, "last_name", None),
                    ],
                )
            ).strip()
            if not name:
                name = user.username or str(user_id)
            return name
        except Exception:
            return str(user_id)

    def _save_config(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            import yaml

            yaml.safe_dump(self.config, f, allow_unicode=True)

    async def _get_user_display_name(self, user_id: int) -> str:
        if not user_id:
            return "Unknown"
        if user_id in self.config.get("users_map", {}):
            return self.config["users_map"][user_id]
        else:
            fetched_name = await self.fetch_user_name(user_id)
            if not self.config.get("users_map", {}):
                self.config["users_map"] = {}
            self.config["users_map"][user_id] = fetched_name
            self._fetched_usernames_count += 1
            if self._fetched_usernames_count % 100 == 0:
                self._save_config()
                self.logger.info(
                    f"Fetched {self._fetched_usernames_count} usernames so far"
                )
            return fetched_name

    async def _get_peer_display_name(self, peer_id: int) -> str:
        if not peer_id:
            return "Unknown"

        if peer_id in self.config.get("users_map", {}):
            return self.config["users_map"][peer_id]
        if peer_id in self.config.get("chats_map", {}):
            return self.config["chats_map"][peer_id]

        entity = None
        try:
            entity = await self.get_entity(peer_id)
        except Exception as e:
            self.logger.debug(f"Failed to get entity {peer_id}: {e}")

        if isinstance(entity, User):
            return await self._get_user_display_name(peer_id)

        if isinstance(entity, (Chat, Channel)):
            name = entity.title or str(peer_id)
            if not self.config.get("chats_map", {}):
                self.config["chats_map"] = {}
            self.config["chats_map"][peer_id] = name
            self._fetched_chatnames_count += 1
            if self._fetched_chatnames_count % 100 == 0:
                self._save_config()
                self.logger.info(
                    f"Fetched {self._fetched_chatnames_count} chat names so far"
                )
            return name

        return await self._get_user_display_name(peer_id)

    def _get_sender_id(self, msg: Dict[str, Any]) -> Optional[int]:
        sender = msg.get("from_id") or msg.get("sender_id") or msg.get("peer_id")
        if isinstance(sender, dict):
            sender = (
                sender.get("user_id")
                or sender.get("channel_id")
                or sender.get("chat_id")
                or sender
            )
        try:
            return int(sender)
        except (TypeError, ValueError):
            return None

    def _get_recipient_id(self, msg: Dict[str, Any]) -> Optional[int]:
        peer = msg.get("peer_id") or msg.get("to_id")
        sender_id = self._get_sender_id(msg)

        if isinstance(peer, dict):
            if "user_id" in peer:
                other_id = peer.get("user_id")
                if self._self_id and sender_id != self._self_id:
                    return self._self_id
                return other_id
            peer = peer.get("channel_id") or peer.get("chat_id") or peer
        try:
            return int(peer)
        except (TypeError, ValueError):
            return None

    async def get_entity(self, identifier: str) -> Optional[Union[User, Chat, Channel]]:
        try:
            if not self.client or not self.client.is_connected():
                await self.connect()

            self.logger.debug(f"Resolving entity: {identifier}")

            if (
                isinstance(identifier, (int, str))
                and str(identifier).lstrip("-").isdigit()
            ):
                id_value = int(identifier)
                self.logger.debug(f"Trying to resolve numeric ID: {id_value}")
                peer_types = [
                    (PeerChannel, "channel/supergroup"),
                    (PeerChat, "basic group"),
                    (PeerUser, "user"),
                ]

                for peer_cls, peer_type in peer_types:
                    try:
                        self.logger.debug(f"Trying to resolve as {peer_type}...")
                        entity = await self.client.get_entity(peer_cls(id_value))
                        self.logger.debug(f"Successfully resolved as {peer_type}")
                        return entity
                    except (ValueError, TypeError, KeyError, ChatIdInvalidError) as e:
                        self.logger.debug(f"Failed to resolve as {peer_type}: {str(e)}")
                        continue
                    except Exception as e:
                        self.logger.debug(
                            f"Unexpected error resolving as {peer_type}: {str(e)}"
                        )
                        continue

                self.logger.warning(
                    f"Could not resolve ID {id_value} as any peer type, trying alternative methods..."
                )

                try:
                    self.logger.debug("Trying to find entity in dialogs...")
                    async for dialog in self.client.iter_dialogs():
                        if hasattr(dialog.entity, "id") and dialog.entity.id == abs(
                            id_value
                        ):
                            self.logger.debug(
                                f"Found entity in dialogs: {dialog.entity}"
                            )
                            return dialog.entity
                except Exception as e:
                    self.logger.debug(f"Error searching in dialogs: {str(e)}")

                try:
                    self.logger.debug("Trying direct entity access...")
                    return await self.client.get_entity(PeerChannel(abs(id_value)))
                except Exception as e:
                    self.logger.debug(f"Direct entity access failed: {str(e)}")

                self.logger.warning(
                    f"Could not find entity with ID {id_value} using any method"
                )
                return None

            self.logger.debug("Trying to resolve as string identifier...")
            try:
                entity = await self.client.get_entity(identifier)
                self.logger.debug("Successfully resolved string identifier")
                return entity
            except Exception as e:
                self.logger.debug(f"Failed to resolve string identifier: {str(e)}")
                raise

        except Exception as e:
            self.logger.error(f"Error getting entity {identifier}: {str(e)}")
            try:
                self.logger.debug("Trying with a fresh connection...")
                await self.client.disconnect()
                await self.connect()
                return await self.client.get_entity(identifier)
            except Exception as e2:
                self.logger.error(f"Second attempt failed: {str(e2)}")
                return None

    async def get_entity_name(self, chat_identifier: str) -> str:
        if not chat_identifier:
            return "chat_history"

        try:
            entity = await self.get_entity(chat_identifier)
            if not entity:
                return None

            if hasattr(entity, "title"):
                name = entity.title
            elif hasattr(entity, "username") and entity.username:
                name = entity.username
            elif hasattr(entity, "first_name") or hasattr(entity, "last_name"):
                name = " ".join(
                    filter(
                        None,
                        [
                            getattr(entity, "first_name", ""),
                            getattr(entity, "last_name", ""),
                        ],
                    )
                )
            else:
                name = str(entity.id)

            safe_name = re.sub(r"[^\w\-_.]", "_", name.strip())
            return safe_name or "chat_history"

        except Exception:
            chat = chat_identifier
            if chat.startswith("@"):
                chat = chat[1:]
            elif "//" in chat:
                chat = chat.split("?")[0].rstrip("/").split("/")[-1]
                if chat.startswith("+"):
                    chat = "invite_" + chat[1:]

            safe_name = re.sub(r"[^\w\-_.]", "_", chat)
            return safe_name or "chat_history"

    async def get_entity_full_name(self, identifier: Union[str, int]) -> str:
        if not identifier:
            return "Unknown"
        try:
            entity = await self.get_entity(identifier)
            if not entity:
                return str(identifier)

            if hasattr(entity, "title"):
                return entity.title
            if hasattr(entity, "first_name") or hasattr(entity, "last_name"):
                name = " ".join(
                    filter(
                        None,
                        [
                            getattr(entity, "first_name", ""),
                            getattr(entity, "last_name", ""),
                        ],
                    )
                ).strip()
                return name or str(identifier)
            if hasattr(entity, "username") and entity.username:
                return entity.username

            return str(identifier)
        except Exception:
            return str(identifier)
