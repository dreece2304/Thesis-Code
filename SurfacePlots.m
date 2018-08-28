%% Making surface plots

clear all 
clc
%% For LOOP


for n = 0.5:0.5:5.5
   Lim = n; 
   row = 2*n;
    for nn = 0:0.01:0.1
        Cap2 = nn;
        col = 100*nn + 1;
        [NPV1(row,col),SOC1avg(row,col), Lifetime(row,col),P_Miss(row,col)] = System([5 Cap2 Lim], 10000000);
        
    end
    
end

%% Acverage state of charge

y = [0.5:0.5:5.5]; x = [0:0.01:0.1];
[X,Y] = meshgrid(x,y);
surf(X,Y,SOC1avg)
zlabel('Average SOC');xlabel('Capacity of Supercapacitor (MWh)');ylabel('Supercapacitor Control Variable (MW)');

%% Lifetime

y = [0.5:0.5:5.5]; x = [0:0.01:0.1];
[X,Y] = meshgrid(x,y);
surf(X,Y,Lifetime)
zlabel('Lifetime (months)');xlabel('Capacity of Supercapacitor (MWh)');ylabel('Supercapacitor Control Variable (MW)');

%% NPV

y = [0.5:0.5:5.5]; x = [0:0.01:0.1];
[X,Y] = meshgrid(x,y);
surf(X,Y,(NPV1))
zlabel('NPV ($)');xlabel('Capacity of Supercapacitor (MWh)');ylabel('Supercapacitor Control Variable (MW)');


%% P Miss

y = [0.5:0.5:5.5]; x = [0:0.01:0.1];
[X,Y] = meshgrid(x,y);
surf(X,Y,(100.*P_Miss))
zlabel('Missed Required Power (%)');xlabel('Capacity of Supercapacitor (MWh)');ylabel('Supercapacitor Control Variable (MW)');

