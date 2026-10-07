import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type Cluster } from "./api";

interface ClusterCtx {
  clusters: Cluster[];
  clusterId: string | null;
  setClusterId: (id: string) => void;
  loading: boolean;
}

const Ctx = createContext<ClusterCtx>({ clusters: [], clusterId: null, setClusterId: () => {}, loading: true });

export function ClusterProvider({ children }: { children: ReactNode }) {
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [clusterId, setClusterId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .clusters()
      .then((cs) => {
        setClusters(cs);
        if (cs.length > 0) setClusterId(cs[0].id);
      })
      .finally(() => setLoading(false));
  }, []);

  return <Ctx.Provider value={{ clusters, clusterId, setClusterId, loading }}>{children}</Ctx.Provider>;
}

export const useCluster = () => useContext(Ctx);
