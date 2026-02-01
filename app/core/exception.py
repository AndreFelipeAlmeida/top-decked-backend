from fastapi import HTTPException

class TopDeckedException:
    @staticmethod
    def bad_request(message: str):
        return HTTPException(
            status_code=400,
            detail=message)
    
    @staticmethod
    def forbidden():
        return HTTPException(
            status_code=403,
            detail="Autenticação negada",
            headers={"WWW-Authenticate": "Bearer"})

    @staticmethod
    def unauthorized():
        return HTTPException(
            status_code=401,
            detail="Permissão negada",
            headers={"WWW-Authenticate": "Bearer"})

    @staticmethod
    def not_found(message: str):
        return HTTPException(
            status_code=404, 
            detail=message)
    