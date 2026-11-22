from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config=SettingsConfigDict(env_file='.env',extra='ignore')
    aws_region:str='ap-southeast-2'
    aws_access_key_id:str=''
    aws_secret_access_key:str=''
    s3_bucket:str=''
    database_url:str=''  
    bedrock_embed_model:str='amazon.titan-embed-text-v2:0'
    bedrock_chat_model:str='amazon.nova-lite-v1:0'
    embed_dim:int=1024
    max_upload_bytes:int=10485760
    pinecone_api_key:str=''
    pinecone_index_name:str='prod-rag-ai-index'
    pinecone_cloud:str='aws'
    pinecone_region:str='us-east-1'
    pinecone_ready_timeout:int=180
    min_relevance:float=0.25
    hitl_enabled:bool=True
    memory_turns:int=6
    auth_secret_key:str='production-rag-auth-secret-key-atlas-enterprise-rag-2026'
    auth_token_expire_hours:int=24
    bedrock_rerank_model:str='cohere.rerank-v3-5:0'
    parent_chunk_size:int=1800
    parent_chunk_overlap:int=200
    child_chunk_size:int=400
    child_chunk_overlap:int=60
    vector_top_k:int=20
    bm25_top_k:int=20
    hybrid_top_k:int=15
    rerank_top_n:int=5
    max_context_chars:int=7500


@lru_cache
def settings() -> Settings:
    return Settings()