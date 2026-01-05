import useWebSocket, { Options } from "react-use-websocket";

const WS_URL = import.meta.env.VITE_WS_BASE_URL;

export const useWS = (path = "", options: Options = {}) => {
  const fullUrl = `${WS_URL}${path}`;
  return useWebSocket(fullUrl, {
    share: true,
    shouldReconnect: () => true,
    ...options,
  } as Options);
};
