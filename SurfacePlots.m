%% Making surface plots


%% For LOOP


for n = 0:0.5:5
   Lim = n; 
   row = 2*n + 1;
    for nn = 0:0.01:0.1
        Cap2 = nn;
        col = 100*nn + 1;
        [NPV1(row,col),SOC1avg(row,col), Lifetime(row,col)] = System([5 Cap2 Lim]);
        
    end
    
end

%% Acverage state of charge

y = [0:0.5:5]; x = [0:0.01:0.1];
[X,Y] = meshgrid(x,y);
surf(X,Y,SOC1avg)
zlabel('Average SOC');xlabel('Capacity of Supercapacitor (MWh)');ylabel('Supercapacitor Control Variable (MW)');

%% Lifetime

y = [0:0.5:5]; x = [0:0.01:0.1];
[X,Y] = meshgrid(x,y);
surf(X,Y,Lifetime)
zlabel('Lifetime (months)');xlabel('Capacity of Supercapacitor (MWh)');ylabel('Supercapacitor Control Variable (MW)');

%% NPV

y = [0:0.5:5]; x = [0:0.01:0.1];
[X,Y] = meshgrid(x,y);
surf(X,Y,(-NPV1))
zlabel('NPV ($)');xlabel('Capacity of Supercapacitor (MWh)');ylabel('Supercapacitor Control Variable (MW)');


