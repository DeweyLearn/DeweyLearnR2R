import logging
import uuid
from typing import Any, AsyncGenerator, Optional, Tuple

from r2r.base import (
    AggregateSearchResult,
    AsyncPipe,
    AsyncState,
    LLMProvider,
    PipeType,
    PromptProvider,
)
from r2r.base.abstractions.llm import GenerationConfig, RAGCompletion

from ..abstractions.generator_pipe import GeneratorPipe

logger = logging.getLogger(__name__)


class SearchRAGPipe(GeneratorPipe):
    class Input(AsyncPipe.Input):
        message: AsyncGenerator[Tuple[str, AggregateSearchResult], None]

    def __init__(
        self,
        llm_provider: LLMProvider,
        prompt_provider: PromptProvider,
        type: PipeType = PipeType.GENERATOR,
        config: Optional[GeneratorPipe] = None,
        *args,
        **kwargs,
    ):
        super().__init__(
            llm_provider=llm_provider,
            prompt_provider=prompt_provider,
            type=type,
            config=config
            or GeneratorPipe.Config(
                name="default_rag_pipe", task_prompt="default_rag"
            ),
            *args,
            **kwargs,
        )

    async def _run_logic(
        self,
        input: Input,
        state: AsyncState,
        run_id: uuid.UUID,
        rag_generation_config: GenerationConfig,
        *args: Any,
        **kwargs: Any,
    ) -> AsyncGenerator[RAGCompletion, None]:
        context = ""
        search_iteration = 1
        total_results = 0
        # must select a query if there are multiple
        sel_query = None
        async for query, search_results in input.message:
            if search_iteration == 1:
                sel_query = query
            context_piece, total_results = await self._collect_context(
                query, search_results, search_iteration, total_results
            )
            context += context_piece
            search_iteration += 1

        messages = self._get_message_payload(sel_query, context)

        response = await self.llm_provider.aget_completion(
            messages=messages, generation_config=rag_generation_config
        )
        yield RAGCompletion(completion=response, search_results=search_results)

        await self.enqueue_log(
            run_id=run_id,
            key="llm_response",
            value=response.choices[0].message.content,
        )

    def _get_message_payload(self, query: str, context: str) -> dict:
        return [
            {
                "role": "system",
                "content": self.prompt_provider.get_prompt(
                    self.config.system_prompt,
                ),
            },
            {
                "role": "user",
                "content": self.prompt_provider.get_prompt(
                    self.config.task_prompt,
                    inputs={
                        "query": query,
                        "context": context,
                    },
                ),
            },
        ]

    async def _collect_context(
        self,
        query: str,
        results: AggregateSearchResult,
        iteration: int,
        total_results: int,
    ) -> Tuple[str, int]:
        context = f"Query:\n{query}\n\n"
        if results.vector_search_results:
            context += f"Vector Search Results({iteration}):\n"
            it = total_results + 1
            for result in results.vector_search_results:
                context += f"[{it}]: {result.metadata['text']}\n\n"
                it += 1
            total_results = (
                it - 1
            )  # Update total_results based on the last index used
        if results.kg_search_results:
            context += f"Knowledge Graph ({iteration}):\n"
            it = total_results + 1
            for query, search_results in results.kg_search_results:  # [1]:
                context += f"Query: {query}\n\n"
                context += f"Results:\n"
                for search_result in search_results:
                    context += f"[{it}]: {search_result}\n\n"
                    it += 1
            total_results = (
                it - 1
            )  # Update total_results based on the last index used
        return context, total_results
